def decimal_to_dms(deg: float, is_lat: bool) -> str:
    abs_deg = abs(deg)
    degrees = int(abs_deg)
    minutes_float = (abs_deg - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60

    hemisphere = (
        "N" if is_lat and deg >= 0 else "S" if is_lat else "E" if deg >= 0 else "W"
    )

    return f"{degrees}° {minutes}' {seconds:.3f}'' {hemisphere}"
