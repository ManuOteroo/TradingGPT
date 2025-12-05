import os
from flask import Flask, request, jsonify
import requests
import base64
from openai import OpenAI
from playwright.sync_api import sync_playwright

app = Flask(__name__)

# --- CONFIGURACIÓN PRINCIPAL ---
# El código lee estas claves de las variables de entorno de Render
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ¡IMPORTANTE! Debes verificar que esta URL funcione para sus gráficos.
# {symbol_encoded} será el activo (ej. BTCUSDT).
# {interval} será el marco de tiempo (ej. W, D, 60).
TRADINGVIEW_URL_TEMPLATE = "https://www.tradingview.com/chart/?symbol={symbol_encoded}&interval={interval}"

# Marcos de tiempo a analizar (Semanal, Diario, 1 Hora)
TIMEFRAMES = [("W", "Semanal"), ("D", "Diario"), ("60", "1 Hora")]

# Inicializar cliente de OpenAI (se autenticará con la clave de entorno)
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    print(f"Error al inicializar OpenAI: {e}")

# --- RUTAS Y FUNCIONES AUXILIARES ---

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    """Maneja la señal de WebHook enviada por TradingView."""
    try:
        data = request.json
        symbol_raw = data.get('symbol', 'UNKNOWN')
        
        if not symbol_raw or symbol_raw == 'UNKNOWN':
            send_telegram_message("❌ Error: Símbolo no recibido. Asegura que el JSON de TradingView contenga el campo 'symbol'.")
            return jsonify({"status": "error", "message": "Symbol missing"}), 400

        # Codificar el símbolo (ej. añade el exchange: BINANCE%3ABTCUSDT)
        # Esto depende de cómo lo espera TradingView. Usaremos el símbolo crudo por simplicidad.
        symbol_encoded = symbol_raw 
        
        # 1. Capturar múltiples gráficos
        image_contents = []
        timeframe_names = []
        
        for tf_code, tf_name in TIMEFRAMES:
            chart_url = TRADINGVIEW_URL_TEMPLATE.format(symbol_encoded=symbol_encoded, interval=tf_code)
            print(f"Capturando: {tf_name} ({chart_url})")
            img_base64 = take_screenshot(chart_url)
            
            if img_base64:
                image_contents.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_base64}"}
                })
                timeframe_names.append(tf_name)
            else:
                # Si falla una captura, notificamos y terminamos el proceso
                send_telegram_message(f"❌ Fallo crítico al capturar el gráfico {symbol_raw} en {tf_name}. Revisar URL en Render.")
                return jsonify({"status": "error", "message": f"Screenshot failed for {tf_name}"}), 500

        # 2. Prompt consolidado para la IA
        prompt_text = (
            f"Analiza este conjunto de {len(timeframe_names)} capturas de pantalla del activo {symbol_raw} "
            f"en los siguientes marcos de tiempo: {', '.join(timeframe_names)}. "
            f"Basado en el análisis de tendencia (largo, medio y corto plazo), patrones y soportes/resistencias: "
            f"1. Resume las conclusiones clave de cada marco de tiempo. "
            f"2. Proporciona una recomendación de trading final, clara y concisa (COMPRA, VENTA o ESPERA) para los próximos días. "
            f"Usa un formato de lista y párrafos cortos para facilitar la lectura."
        )
        
        # 3. Combinar el prompt de texto con las imágenes para GPT-4 Vision
        messages_for_gpt = [{"type": "text", "text": prompt_text}] + image_contents

        # 4. Llamar a GPT-4 Vision
        analysis = analyze_with_gpt4(messages_for_gpt)

        # 5. Enviar el resultado a Telegram
        send_telegram_message(f"🚨 **ANÁLISIS IA RÁPIDO para {symbol_raw}** 🚨\n\n{analysis}")

        return jsonify({"status": "success", "analysis": analysis}), 200

    except Exception as e:
        print(f"Error general en el proceso: {e}")
        send_telegram_message(f"❌ Error crítico en la automatización: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def take_screenshot(url):
    """Automatiza la navegación a la URL y toma la captura del gráfico."""
    try:
        with sync_playwright() as p:
            # Lanzamos el navegador en modo sin cabeza (headless=True)
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            # Definir un tamaño para que la captura sea consistente
            page.set_viewport_size({"width": 1280, "height": 720}) 
            
            # Navegar a la URL de TradingView
            page.goto(url, timeout=60000)
            
            # Esperar a que el gráfico cargue (usando el selector principal del gráfico)
            page.wait_for_selector(".chart-container", timeout=20000) 
            
            # Espera adicional para que todos los indicadores carguen completamente
            page.wait_for_timeout(5000) 
            
            # Tomar la captura del área específica del gráfico
            screenshot_bytes = page.locator(".chart-container").screenshot(type="png") 
            browser.close()
            
            return base64.b64encode(screenshot_bytes).decode('utf-8')
    except Exception as e:
        print(f"Error en la captura de pantalla de {url}: {e}")
        return None


def analyze_with_gpt4(messages_content):
    """Llama a la API de OpenAI con el prompt y las imágenes."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": messages_content}],
        max_tokens=1000,
    )
    return response.choices[0].message.content


def send_telegram_message(message):
    """Envía un mensaje al chat de Telegram usando el token y el chat ID."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    requests.post(url, data=payload)

if __name__ == '__main__':
    # Para pruebas locales, descomentar y usar un puerto diferente
    # app.run(debug=True, port=10000) 
    pass