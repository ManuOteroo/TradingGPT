import os
import sys
import time
import requests
import base64
import json
from openai import OpenAI
from playwright.sync_api import sync_playwright
from datetime import datetime

# --- CONFIGURACIÓN ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

USER_DATA_DIR = r"C:\Users\manuu\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default" 
CONTEXT_FILE_PATH = "intraday_context.txt"
CAPTURES_DIR = "capturas_ia"
SP500_SYMBOL = "ES1!" 
TRADINGVIEW_URL_TEMPLATE = "https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}"

LOOP_INTERVAL = 600 # 10 minutos
CONTEXT_REFRESH_INTERVAL = 24 

client = OpenAI(api_key=OPENAI_API_KEY)

def send_telegram_message(message):
    """Envía señales de COMPRA/VENTA de inmediato sin filtros de repetición."""
    msg_upper = message.upper()
    
    if "COMPRA" in msg_upper or "VENTA" in msg_upper:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        try:
            requests.post(url, data=payload)
            print(f"📢 SEÑAL DISPARADA A TELEGRAM")
        except Exception as e:
            print(f"Error Telegram: {e}")
    else:
        print("ℹ️ CICLO FINALIZADO: Espera técnica confirmada.")

def take_screenshot(context, url, tf_name):
    try:
        page = context.new_page()
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto(url, timeout=60000)
        page.wait_for_selector(".chart-container", timeout=20000) 
        time.sleep(8) 
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        filename = os.path.join(CAPTURES_DIR, f"last_{tf_name}.png")
        screenshot_bytes = page.screenshot(type="png", path=filename) 
        page.close()
        return base64.b64encode(screenshot_bytes).decode('utf-8')
    except Exception as e:
        print(f"Error captura {tf_name}: {e}")
        return None

def analyze_with_gpt4(prompt, images):
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}] + images}]
    response = client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=1000)
    return response.choices[0].message.content

def run_analysis(mode):
    timeframes = [("240", "H4"), ("60", "H1")] if mode == "contexto" else [("5", "M5"), ("1", "M1")]
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] >>> INICIANDO {mode.upper()}")
    image_contents = []
    
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR, headless=True, args=["--no-sandbox"]
            )
            for tf_code, tf_name in timeframes:
                url = TRADINGVIEW_URL_TEMPLATE.format(symbol=SP500_SYMBOL, interval=tf_code)
                print(f"Capturando {tf_name}...")
                img = take_screenshot(context, url, tf_name)
                if img:
                    image_contents.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}})
            context.close()
    except Exception as e:
        print(f"Error Playwright: {e}")
        return

    if mode == "contexto":
        prompt = (
            "ERES EL ESTRATEGA JEFE. Define tendencia H4/H1 y niveles clave.\n"
            "Tu análisis servirá de base para que el ejecutor dispare órdenes."
        )
        analysis = analyze_with_gpt4(prompt, image_contents)
        with open(CONTEXT_FILE_PATH, "w", encoding="utf-8") as f: f.write(analysis)
        print("\n=== HOJA DE RUTA ACTUALIZADA ===\n" + analysis + "\n================================")
    
    else:
        if not os.path.exists(CONTEXT_FILE_PATH): return
        with open(CONTEXT_FILE_PATH, "r", encoding="utf-8") as f: context_macro = f.read()
        
        # PROMPT DE EJECUCIÓN CON ANÁLISIS OBLIGATORIO
        prompt = (
            "ERES EL EJECUTOR TÁCTICO. Tu misión es decidir si disparamos una orden AHORA MISMO.\n"
            f"REGLAS DEL ESTRATEGA:\n{context_macro}\n\n"
            "MISION:\n"
            "1. Describe brevemente qué hace el precio ahora mismo en M5/M1 (Estructura y volumen).\n"
            "2. Evalúa si el precio actual es apto para entrar YA MISMO siguiendo al estratega.\n"
            "3. Si es apto, da la orden de COMPRA o VENTA con Entrada (Precio Actual), SL y TP.\n"
            "4. Si NO es apto, explica por qué (ej: 'Precio en medio del rango') y di ESPERA.\n\n"
            "**FORMATO DE SALIDA:**\n"
            "- BREVE ANÁLISIS: (Máximo 3 líneas).\n"
            "- INSTRUCCIÓN FINAL: [COMPRA / VENTA / ESPERA]"
        )
        analysis = analyze_with_gpt4(prompt, image_contents)
        print("\n--- ANÁLISIS INTRADÍA ---\n" + analysis + "\n-------------------------")
        send_telegram_message(analysis)

if __name__ == '__main__':
    print("🤖 Bot de Ejecución Directa Activado")
    ciclos = 0
    while True:
        if ciclos % CONTEXT_REFRESH_INTERVAL == 0:
            run_analysis("contexto")
        run_analysis("intradia")
        ciclos += 1
        
        for i in range(LOOP_INTERVAL, 0, -1):
            sys.stdout.write(f"\r ⏳ Próximo análisis en: {i//60:02d}:{i%60:02d} ")
            sys.stdout.flush()
            time.sleep(1)
        sys.stdout.write("\r" + " " * 50 + "\r")