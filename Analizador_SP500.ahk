; --- CONFIGURACIÓN DE RUTAS ---
; Verifica que estas rutas sean correctas en tu PC
PyExe := "C:\Users\manuu\AppData\Local\Programs\Python\Python314\python.exe"
ScriptPath := "C:\Repositorios\TradingGPT\app.py"
; ------------------------------


; 1. Atajo para Contexto Lento (4H/1H)
; Tecla: Control + Alt + C
^!c::
{
    TrayTip, Contexto Mayor, Generando análisis 4H/1H (Modo Lento). Esto se hace una vez al día., 5, 1
    ; 🔴 ¡ESTA LÍNEA DEBE ENVIAR LA PALABRA "contexto"!
    Run, %PyExe% "%ScriptPath%" contexto
}
return

; 2. Atajo para Análisis Intradía Rápido (1M/5M)
; Tecla: Control + Alt + A
^!a::
{
    TrayTip, Análisis IA Rápido, Analizando 1M/5M con contexto guardado., 5, 1
    ; Esta línea envía la palabra "intradia"
    Run, %PyExe% "%ScriptPath%" intradia
}
return