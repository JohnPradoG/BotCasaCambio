from app.config.settings import Settings
from app.services.self_test import example_alert, real_status


def test_example_alert_is_labeled_and_profitable():
    text = example_alert(Settings(_env_file=None))
    assert text.startswith("🧪 PRUEBA: casas y precios INVENTADOS")
    assert "🔥 ARBITRAJE: +$" in text and "+$20.833" in text
    assert "Casa Ejemplo A" in text and "ejemplo_a" not in text


def test_example_alert_survives_old_margins():
    text = example_alert(Settings(_env_file=None, safety_margin_percent=0.5, min_net_profit_clp=10_000))
    assert "🔥 ARBITRAJE: +$" in text


def test_real_status_warns_about_old_settings():
    assert "falta pegar la línea" in real_status(0, 10_000, 0.5, None)
    ok = real_status(2, 0, 0, "• PEN: comprar en X a 280 y vender en Y a 284 → +$14.285")
    assert "Rutas con ganancia: 2 (te llegaría alerta)" in ok and "Lo más cerca: PEN" in ok
    assert "falta pegar" not in ok
