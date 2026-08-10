from pakhi.risk.alerts import AlertManager, AlertSeverity


def test_alerts_heatwave_low():
    mgr = AlertManager()
    temps = [39.0, 39.0, 20.0, 20.0]
    alert = mgr.check_heatwave({"temperature_forecast": temps}, threshold=38.0, days=2)
    assert alert.severity == AlertSeverity.LOW


def test_alerts_drought_high():
    mgr = AlertManager()
    spi = [-2.5] * 30
    alert = mgr.check_drought({"spi_values": spi}, threshold=-1.5, days=30)
    assert alert.severity == AlertSeverity.HIGH


def test_alerts_drought_low():
    mgr = AlertManager()
    # Need 30 days below -1.5, but mean > -1.5? Not possible if all 30 days are below -1.5, mean will be < -1.5.
    # Ah, what if we have 30 days below -1.5, and 300 days of +10?
    spi = [-2.0] * 30 + [10.0] * 300
    alert = mgr.check_drought({"spi_values": spi}, threshold=-1.5, days=30)
    assert alert.severity == AlertSeverity.LOW
