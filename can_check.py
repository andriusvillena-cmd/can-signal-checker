"""can-signal-checker: valida un log CAN contra su matriz DBC.

Uso:
    python can_check.py <log.asc> <matriz.dbc> [segundos_maximos]

Comprueba tres cosas:
    1. Timeout        - un mensaje deja de transmitirse
    2. Contador       - el contador rodante no incrementa de uno en uno
    3. Plausibilidad  - una rueda parada con el vehiculo en movimiento
"""

import sys

import can
import cantools
import numpy as np
import pandas as pd

# Ciclo nominal de cada mensaje, en milisegundos
CICLOS_MS = {
    "BRAKE_01":        10,
    "STEERING_01":     10,
    "WHEEL_SPEEDS_01": 20,
    "VEHICLE_DYN_01":  20,
}

# Se declara timeout cuando el hueco supera este numero de ciclos
FACTOR_TIMEOUT = 5

# Contadores rodantes: mensaje -> senal
CONTADORES = {
    "BRAKE_01":        "Brake_Alive_Counter",
    "WHEEL_SPEEDS_01": "Wheel_Alive_Counter",
    "STEERING_01":     "Steering_Alive_Counter",
}


def cargar_log(ruta_log, ruta_dbc):
    """Decodifica el log entero y devuelve una tabla, una fila por trama."""
    db = cantools.database.load_file(ruta_dbc)
    filas = []

    with can.ASCReader(ruta_log) as lector:
        for trama in lector:
            try:
                mensaje = db.get_message_by_frame_id(trama.arbitration_id)
            except KeyError:
                continue                      # ID que no esta en el DBC

            fila = {"t": trama.timestamp, "mensaje": mensaje.name}
            fila.update({n: float(v) for n, v in mensaje.decode(trama.data).items()})
            filas.append(fila)

    return pd.DataFrame(filas)


def comprobar_timeout(tabla, nombre, ciclo_ms):
    """Un mensaje que deja de llegar durante mas de FACTOR_TIMEOUT ciclos."""
    tramas = tabla[tabla["mensaje"] == nombre]
    if len(tramas) < 2:
        return None

    instantes = tramas["t"].to_numpy()
    huecos = np.diff(instantes) * 1000
    limite = ciclo_ms * FACTOR_TIMEOUT

    if huecos.max() <= limite:
        return None

    peor = int(np.argmax(huecos))
    return {
        "tipo": "timeout",
        "donde": nombre,
        "inicio": float(instantes[peor]),
        "fin": float(instantes[peor + 1]),
        "detalle": f"hueco de {huecos.max():.0f} ms, ciclo nominal {ciclo_ms} ms",
    }


def comprobar_contador(tabla, nombre, senal):
    """El contador rodante debe incrementar de uno en uno, modulo 16."""
    tramas = tabla[tabla["mensaje"] == nombre]
    if len(tramas) < 2 or senal not in tramas:
        return None

    instantes = tramas["t"].to_numpy()
    valores = tramas[senal].to_numpy()

    saltos = [i for i in range(1, len(valores))
              if (valores[i] - valores[i - 1]) % 16 != 1]

    if not saltos:
        return None

    primero = saltos[0]
    return {
        "tipo": "contador",
        "donde": f"{nombre}.{senal}",
        "inicio": float(instantes[primero]),
        "fin": float(instantes[saltos[-1]]),
        "detalle": f"{len(saltos)} saltos, el primero {int(valores[primero - 1])} -> {int(valores[primero])}",
    }


def comprobar_plausibilidad(tabla):
    """Una rueda parada mientras las otras giran no es fisicamente posible."""
    ruedas = tabla[tabla["mensaje"] == "WHEEL_SPEEDS_01"]
    if ruedas.empty:
        return None

    nombres = ["Wheel_Speed_FL", "Wheel_Speed_FR", "Wheel_Speed_RL", "Wheel_Speed_RR"]
    hallazgos = []

    for parada in nombres:
        otras = [n for n in nombres if n != parada]
        sospechosas = ruedas[(ruedas[parada] < 1.0) & (ruedas[otras].min(axis=1) > 5.0)]

        if sospechosas.empty:
            continue

        hallazgos.append({
            "tipo": "plausibilidad",
            "donde": parada,
            "inicio": float(sospechosas["t"].iloc[0]),
            "fin": float(sospechosas["t"].iloc[-1]),
            "detalle": f"{len(sospechosas)} tramas a 0 km/h con las otras tres girando",
        })

    return hallazgos


def analizar(tabla):
    """Pasa las tres comprobaciones y devuelve la lista de hallazgos."""
    hallazgos = []

    for nombre, ciclo in CICLOS_MS.items():
        hallazgo = comprobar_timeout(tabla, nombre, ciclo)
        if hallazgo:
            hallazgos.append(hallazgo)

    for nombre, senal in CONTADORES.items():
        hallazgo = comprobar_contador(tabla, nombre, senal)
        if hallazgo:
            hallazgos.append(hallazgo)

    hallazgos.extend(comprobar_plausibilidad(tabla) or [])

    hallazgos.sort(key=lambda h: h["inicio"])
    return hallazgos


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    ruta_log, ruta_dbc = sys.argv[1], sys.argv[2]

    tabla = cargar_log(ruta_log, ruta_dbc)

    if len(sys.argv) > 3:
        limite = float(sys.argv[3])
        tabla = tabla[tabla["t"] <= limite]
        print(f"Analizando solo hasta t = {limite} s")

    hallazgos = analizar(tabla)

    print(f"\n{ruta_log}")
    print(f"{len(tabla)} tramas   {tabla['t'].max():.2f} s   {len(hallazgos)} hallazgos\n")

    if not hallazgos:
        print("  Sin hallazgos. Comunicacion correcta.")
        return

    for h in hallazgos:
        print(f"  {h['tipo']:15} {h['donde']:28} "
              f"{h['inicio']:6.2f} - {h['fin']:6.2f} s   {h['detalle']}")


main()
