import os
import requests
import base64
from openai import OpenAI
from playwright.sync_api import sync_playwright
import time
from datetime import datetime
import sys 

# Estas claves deben estar definidas en las Variables de Entorno de Windows
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

#Debe apuntar a la carpeta de datos del navegador con la sesión de TradingView.
USER_DATA_DIR = r"C:\Users\manuu\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default" 

CONTEXT_FILE_PATH = "intraday_context.txt"
SP500_SYMBOL = "ES1!" 
TRADINGVIEW_URL_TEMPLATE = "https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}"

# SEPARACIÓN DE MARCOS DE TIEMPO
CONTEXT_TIMEFRAMES = [
    ("240", "4 Horas"), # H4
    ("60", "1 Hora")    # H1
]

INTRADAY_TIMEFRAMES = [
    ("5", "5 Minutos"), # M5
    ("1", "1 Minuto")   # M1
]

# Inicializar cliente de OpenAI
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    print(f"Error al inicializar OpenAI. Verifica la clave API en Variables de Entorno: {e}")
    exit()


def send_telegram_message(message):
    """Envía un mensaje al chat de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    requests.post(url, data=payload)

def take_screenshot(context, url, tf_name):
    """Automatiza la navegación y toma la captura del gráfico."""
    try:
        page = context.new_page()
        page.set_viewport_size({"width": 1280, "height": 720})
        
        page.goto(url, timeout=60000)
        page.wait_for_selector(".chart-container", timeout=20000) 
        page.wait_for_timeout(3000) 
        
        screenshot_bytes = page.locator(".chart-container").screenshot(type="png") 
        page.close()
        
        return base64.b64encode(screenshot_bytes).decode('utf-8')
    except Exception as e:
        print(f"Error en la captura de pantalla de {tf_name}: {e}")
        send_telegram_message(f"Fallo al capturar el gráfico {tf_name}. Revisa la sesión de TV ({tf_name}).")
        return None

def analyze_with_gpt4(messages_content):
    """Llama a la API de OpenAI con el prompt y las imágenes."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": messages_content}],
        max_tokens=1000,
    )
    return response.choices[0].message.content


def save_context_to_file(analysis_text):
    """Guarda el análisis de contexto de 4H/1H en un archivo local."""
    try:
        with open(CONTEXT_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(analysis_text)
        print(f"Contexto guardado en {CONTEXT_FILE_PATH}")
    except Exception as e:
        print(f"Error al guardar el contexto: {e}")

def load_context_from_file():
    """Carga el análisis de contexto de 4H/1H desde un archivo local."""
    try:
        if not os.path.exists(CONTEXT_FILE_PATH):
            return None
        with open(CONTEXT_FILE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error al cargar el contexto: {e}")
        return None

# --- FUNCIÓN PRINCIPAL DE EJECUCIÓN (DUAL MODE) ---

def run_analysis(mode):
    """Ejecuta el proceso completo de captura, análisis y notificación según el modo."""
    start_time = time.time()
    
    # 1. Validación y Selección de Modo
    if not all([OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, USER_DATA_DIR, SP500_SYMBOL]):
        print("ERROR: Claves o rutas faltantes.")
        send_telegram_message("Error: Faltan claves en las Variables de Entorno de Windows o la ruta de configuración en el código.")
        return
    
    if mode == "contexto":
        timeframes_to_use = CONTEXT_TIMEFRAMES
        action_name = "GENERACIÓN DE CONTEXTO (4H/1H)"
    elif mode == "intradia":
        timeframes_to_use = INTRADAY_TIMEFRAMES
        action_name = "ANÁLISIS INTRADÍA RÁPIDO (1M/5M)"
    else:
        print("Modo no reconocido. Usa 'contexto' o 'intradia'.")
        return

    tf_list = ", ".join([tf[1] for tf in timeframes_to_use])
    send_telegram_message(f"**[{action_name} INICIADO {datetime.now().strftime('%H:%M:%S')}]**\nCapturando {SP500_SYMBOL} ({tf_list})...")
    
    symbol_raw = SP500_SYMBOL
    image_contents = []
    timeframe_names = []
    
    # CAPTURA DE PANTALLA
    try:
        with sync_playwright() as p:
            #Usa el contexto persistente del navegador
            context = p.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR, 
                headless=True,  
                args=["--no-sandbox"]
            )
            
            for tf_code, tf_name in timeframes_to_use:
                chart_url = TRADINGVIEW_URL_TEMPLATE.format(symbol=symbol_raw, interval=tf_code)
                print(f"Capturando: {tf_name}")
                img_base64 = take_screenshot(context, chart_url, tf_name)
                
                if img_base64:
                    image_contents.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_base64}"}
                    })
                    timeframe_names.append(tf_name)
                else:
                    print(f"--- Error en la captura de {tf_name}. Proceso detenido. ---")
                    context.close()
                    return 
            
            context.close() 

    except Exception as e:
        print(f"Error durante la ejecución de Playwright: {e}")
        send_telegram_message(f"Error grave en la inicialización de Playwright: {e}")
        return
    
    if len(image_contents) != len(timeframes_to_use):
        send_telegram_message("Error: No se pudieron capturar todos los marcos de tiempo.")
        return
    
    #  PROMPT Y ANÁLISIS (DIFERENCIADO POR MODO)
    
    if mode == "contexto":
        # PROMPT para Analista Macro (Generar texto limpio para inyección)
        prompt_text = (
            "ERES EL ANALISTA MACRO. Tu única tarea es generar un resumen de texto que servirá como Contexto de Mercado (H4/H1) "
            "para otro modelo de IA que realizará el Scalping intradía. Tu salida debe ser estrictamente concisa y no incluir juicios de valor sobre la entrada.\n\n"
            
            f"Aquí tienes {len(timeframes_to_use)} capturas de pantalla del activo {symbol_raw} "
            f"en los marcos de tiempo {', '.join(timeframe_names)} (H4 y H1). "
            "Analiza las imágenes bajo el siguiente formato y con el enfoque del trader:\n\n"
            
            "**FORMATO REQUERIDO (Solo el texto de las secciones):**\n"
            "**1. TENDENCIA Y SESGO MACRO:** Define la tendencia principal observada en H4. (Ej: Alcista/Bajista/Lateral). Establece el sesgo inicial para el intradía (Ej: Sesgo Comprador por encima de [Nivel]).\n"
            "**2. ESTRUCTURA RECIENTE H1:** Describe la estructura de precios en H1 (Máximos/Mínimos crecientes o decrecientes) y la dirección que domina la última hora.\n"
            "**3. NIVELES CLAVE DE LIQUIDEZ:** Identifica las dos Zonas de S/R o Máximos/Mínimos que actúan como límites críticos para la sesión intradía. (Ej: Resistencia Clave: [Nivel X], Soporte Clave: [Nivel Y]).\n"
            "**4. POSICIÓN RELATIVA VWAP:** Describe si el precio está cotizando por encima o por debajo del VWAP semanal/diario visible en H1 y qué implica esto (Ej: Cotizando por encima, confirmando la zona de valor superior).\n"
            "**5. SÍNTESIS GENERAL:** Resumen de una línea del panorama completo. (Ej: Se mantiene la estructura alcista mientras no se rompa [Nivel Crítico de Soporte]).\n"
            
            "Tu respuesta debe ser únicamente el contenido de estas cinco secciones, sin títulos, introducciones o explicaciones adicionales."
        )
        
        messages_for_gpt = [{"type": "text", "text": prompt_text}] + image_contents
        analysis = analyze_with_gpt4(messages_for_gpt)
        
        save_context_to_file(analysis) 
        
        end_time = time.time()
        duration = round(end_time - start_time, 1)
        
        send_telegram_message(f"**Contexto de {SP500_SYMBOL} (4H/1H) Actualizado** ({duration}s).\n\n"
                              f"El análisis de contexto es:\n{analysis}")
        print("Contexto actualizado y enviado a Telegram.")
        
    elif mode == "intradia":
        context_text = load_context_from_file() 
        
        if not context_text:
            send_telegram_message("**ERROR: Contexto 4H/1H no encontrado.** Por favor, ejecuta el script primero en modo Contexto.")
            return
            
        # PROMPT para Mentor Trader (Análisis de ejecución inyectando contexto)
        prompt_text = (
            # CONTEXTO INICIAL Y ROL
            "ERES MI MENTOR TRADER y operamos futuros del S&P 500 (ES/MES) en una estrategia de Scalping/Day Trading. "
            "Nuestro enfoque se centra en la Acción del Precio, Volumen, Estructura (máximos/mínimos) y Zonas de Liquidez. "
            "El VWAP se usa ÚNICAMENTE como referencia institucional o de zona de valor, nunca para señales de entrada por cruces. "
            "Solo buscamos secciones limpias del movimiento. Trabajamos exclusivamente con la información visual y textual que te proporciono.\n\n"
            
            # CONTEXTO MACRO (CARGADO DEL ARCHIVO)
            f"**CONTEXTO DE ESTRUCTURA MAYOR (H4/H1) PREVIAMENTE ANALIZADO:**\n---\n{context_text}\n---\n\n"
            
            # ANÁLISIS DE LAS CAPTURAS DE EJECUCIÓN
            f"Aquí tienes {len(timeframes_to_use)} capturas de pantalla del activo {symbol_raw} "
            f"en los marcos de tiempo de ejecución ({', '.join(timeframe_names)}). "
            "Analiza estas capturas a la luz del CONTEXTO MACRO proporcionado y sigue las siguientes reglas para la ejecución:\n\n"
            
            # REGLAS DE EJECUCIÓN Y CONFIRMACIONES
            "**REGLAS DE DECISIÓN (PRÁCTICAS Y DIRECTAS):**\n"
            "• **Estructura:** Evalúa si la micro-estructura actual (M5/M1) está alineada con el Contexto Mayor (H4/H1).\n"
            "• **Zonas:** Identifica zonas de soporte/resistencia/liquidez relevantes en los gráficos de ejecución.\n"
            "• **Confirmación (El Gatillo):** Busca patrones sencillos y claros de reversión o continuación:\n"
            "  - **Rechazo:** Mechas largas + volumen en soportes/resistencias.\n"
            "  - **Pullback:** Retroceso a una zona previamente rota (soporte -> resistencia o viceversa) con un rechazo claro.\n"
            "  - **Patrón Doble:** Doble techo/fondo con ruptura clara del nivel intermedio.\n"
            "• **VOLUMEN:** El volumen debe ser una confirmación activa de la intención de los grandes participantes en las zonas clave.\n\n"
            
            #FORMATO DE SALIDA (PROCESO CONSTANTE)
            "**PROCESO DE MODO TRADER (DEBES SEGUIR ESTE FORMATO SIEMPRE):**\n"
            "Genera tu respuesta final en tres secciones obligatorias y concisas:\n"
            "1. **RESUMEN CONTEXTUAL:** 1-2 líneas que validen si el Contexto Mayor se está respetando y qué zonas son críticas ahora mismo.\n"
            "2. **ANÁLISIS INTRADÍA DETALLADO:** Un análisis de la acción del precio y el volumen en M5/M1, indicando el sesgo direccional (Alcista/Bajista/Lateral) y la justificación de la entrada.\n"
            "3. **RECOMENDACIÓN FINAL:** Una única palabra clave y directa basada en tu análisis: **COMPRA**, **VENTA** o **ESPERA** (si las condiciones no son claras o hay ruido)."
        )
        
        messages_for_gpt = [{"type": "text", "text": prompt_text}] + image_contents
        analysis = analyze_with_gpt4(messages_for_gpt)

        end_time = time.time()
        duration = round(end_time - start_time, 1)
        
        send_telegram_message(f"**ANÁLISIS INTRADÍA COMPLETADO ({duration}s)**\n\n**Activo:** {symbol_raw}\n\n{analysis}")
        print("Análisis Intradía enviado a Telegram.")


if __name__ == '__main__':
    print("--- Proceso de Análisis Iniciado ---")
    
    if len(sys.argv) > 1:
        execution_mode = sys.argv[1].lower() 
    else:
        execution_mode = "intradia" 
    
    print(f"Modo de ejecución detectado: {execution_mode}")
    run_analysis(execution_mode)
    print("--- Proceso Finalizado ---")