from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import date
import time
import os
import sys

DOWNLOAD_DIR = os.environ.get("PORTAL_DOWNLOAD_DIR", "")
USUARIO      = os.environ.get("PORTAL_USUARIO", "")
SENHA        = os.environ.get("PORTAL_SENHA", "")

if not DOWNLOAD_DIR or not USUARIO or not SENHA:
    print("[ERRO] Credenciais nao configuradas. Execute via web app.")
    sys.exit(1)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

chrome_options = Options()
chrome_options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True,
    "profile.default_content_setting_values.automatic_downloads": 1
})
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
driver.execute_cdp_cmd("Browser.setDownloadBehavior", {
    "behavior": "allow",
    "downloadPath": DOWNLOAD_DIR,
    "eventsEnabled": True,
})
driver.get("https://portal.unimedpalmas.coop.br/index.jsp")

time.sleep(5)

try:
    alert = driver.switch_to.alert
    print(f"Alert inicial: {alert.text}")
    alert.accept()
    print("Alert inicial fechado.")
    time.sleep(2)
except Exception:
    pass

# ── LOGIN ─────────────────────────────────────────────────────────────────────
driver.switch_to.frame(0)
driver.switch_to.frame(1)

wait = WebDriverWait(driver, 10)

Select(driver.find_element(By.ID, "tipoUsuario")).select_by_value("P")
wait.until(EC.presence_of_element_located((By.ID, "prestador")))
time.sleep(2)

driver.find_element(By.ID, "nmUsuario").send_keys(USUARIO)
driver.find_element(By.ID, "dsSenha").send_keys(SENHA)

botao_entrar = wait.until(EC.element_to_be_clickable((By.ID, "btn_entrar")))
botao_entrar.click()

print("Login enviado, verificando acesso...", flush=True)
time.sleep(3)

try:
    alert = driver.switch_to.alert
    msg = alert.text
    alert.accept()
    print(f"[LOGIN_FAILED] {msg}", flush=True)
    driver.quit()
    sys.exit(2)
except Exception:
    pass

time.sleep(3)
print("Login efetuado, aguardando portal carregar...", flush=True)

# ── HELPER: entrar no frame#menuLateral ───────────────────────────────────────
def entrar_menu_lateral():
    driver.switch_to.default_content()
    driver.switch_to.frame(driver.find_element(By.TAG_NAME, "iframe"))
    driver.switch_to.frame(driver.find_element(By.NAME, "principal"))
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    iframe_ppl = next((f for f in iframes if "principalPrestador" in (f.get_attribute("src") or "")), iframes[-1])
    driver.switch_to.frame(iframe_ppl)
    driver.switch_to.frame(driver.find_element(By.ID, "menuLateral"))

# ── HELPER: entrar no frame#paginaPrincipal ───────────────────────────────────
def entrar_pagina_principal():
    driver.switch_to.default_content()
    driver.switch_to.frame(driver.find_element(By.TAG_NAME, "iframe"))
    driver.switch_to.frame(driver.find_element(By.NAME, "principal"))
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    iframe_ppl = next((f for f in iframes if "principalPrestador" in (f.get_attribute("src") or "")), iframes[-1])
    driver.switch_to.frame(iframe_ppl)
    driver.switch_to.frame(driver.find_element(By.ID, "paginaPrincipal"))

# ── CLICAR EM COMUNICADOS > VISUALIZAR COMUNICADOS ───────────────────────────
entrar_menu_lateral()

comunicados = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "item_9")))
driver.execute_script("arguments[0].click();", comunicados)
print("Clicado em: Comunicados")
time.sleep(1)

subitem = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "subItem_9_1")))
driver.execute_script("arguments[0].click();", subitem)
print("Clicado em: Visualizar comunicados (subItem_9_1)")

time.sleep(4)

# ── LER CONTEUDO EM paginaPrincipal ──────────────────────────────────────────
entrar_pagina_principal()

# ── PREENCHER DATAS DO FILTRO ─────────────────────────────────────────────────
data_de  = "01/09/2025"
data_ate = date.today().strftime("%d/%m/%Y")

campo_inicio = driver.find_element(By.ID, "dtInicio")
campo_fim    = driver.find_element(By.ID, "dtFim")

driver.execute_script(f"arguments[0].value = '{data_de}';", campo_inicio)
print(f"Data de: {data_de}")

driver.execute_script("arguments[0].removeAttribute('readonly');", campo_fim)
driver.execute_script(f"arguments[0].value = '{data_ate}';", campo_fim)
print(f"Data ate: {data_ate}")

# ── CLICAR EM CONSULTAR ───────────────────────────────────────────────────────
btn_consultar = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((By.XPATH,
        "//input[@value='Consultar'] | //button[contains(text(),'Consultar')] | //a[contains(text(),'Consultar')]"
    ))
)
driver.execute_script("arguments[0].click();", btn_consultar)
print("\nClicado em: Consultar")
time.sleep(4)

# Fechar alert se aparecer
try:
    alert = driver.switch_to.alert
    print(f"Alert: {alert.text}")
    alert.accept()
    print("Alert fechado. Nenhum resultado encontrado.")
    driver.quit()
    exit()
except Exception:
    pass

print("\nResultados:")
links2 = driver.find_elements(By.TAG_NAME, "a")
for l in links2:
    texto = l.text.strip()
    href  = l.get_attribute("href") or ""
    if texto:
        print(f"  '{texto}' -> {href[:120]}")

# ── CLICAR NO BOTAO (+) DO COMUNICADO ────────────────────────────────────────
time.sleep(1)
btn_mais = None

candidates = driver.find_elements(By.XPATH, "//input[@value='+'] | //img[contains(@src,'mais') or contains(@src,'plus') or contains(@src,'expand') or contains(@alt,'+')]")
if candidates:
    btn_mais = candidates[0]

if btn_mais is None:
    candidates = driver.find_elements(By.XPATH, "//*[normalize-space(text())='+']")
    if candidates:
        btn_mais = candidates[0]

if btn_mais is None:
    candidates = driver.find_elements(By.XPATH, "//*[@onclick and (contains(@onclick,'detalhe') or contains(@onclick,'expand') or contains(@onclick,'abre') or contains(@onclick,'show'))]")
    if candidates:
        btn_mais = candidates[-1]

if btn_mais:
    print(f"\nBotao (+) encontrado: tag='{btn_mais.tag_name}'")
    driver.execute_script("arguments[0].click();", btn_mais)
    print("Clicado no botao (+)!")
    time.sleep(3)
else:
    print("\nBotao (+) nao encontrado automaticamente.")
    clickables = driver.find_elements(By.XPATH, "//*[@onclick]")
    for c in clickables:
        print(f"  tag='{c.tag_name}' id='{c.get_attribute('id') or ''}' onclick='{(c.get_attribute('onclick') or '')[:120]}'")

print("\nTexto da pagina apos clicar no (+):")
print(driver.find_element(By.TAG_NAME, "body").text.strip()[:1000])

# ── CLICAR NOS LINKS DE DOWNLOAD (anexos do comunicado) ──────────────────────
time.sleep(1)
links_pagina = driver.find_elements(By.TAG_NAME, "a")
links_download = [l for l in links_pagina if l.text.strip() and "Lista" in l.text]

print(f"\nLinks de download encontrados: {len(links_download)}")
for l in links_download:
    print(f"  '{l.text.strip()}' -> {l.get_attribute('href') or ''}")

for i, link in enumerate(links_download):
    nome = link.text.strip()
    existentes = [f for f in os.listdir(DOWNLOAD_DIR) if os.path.splitext(f)[0] == nome]
    if existentes:
        print(f"\nArquivo '{existentes[0]}' ja existe na pasta de downloads. Ignorando.")
        continue

    print(f"\nBaixando [{i+1}/{len(links_download)}]: '{nome}'")
    driver.execute_script("arguments[0].click();", link)
    time.sleep(8)

# Aguardar conclusao dos downloads (max 60s)
print(f"\nAguardando downloads em: {DOWNLOAD_DIR}")
for _ in range(60):
    em_andamento = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".crdownload")]
    if em_andamento:
        print(f"  Baixando... {em_andamento}")
        time.sleep(1)
    else:
        break

arquivos_finais = [f for f in os.listdir(DOWNLOAD_DIR) if not f.startswith(".")]
print(f"\nArquivos em '{DOWNLOAD_DIR}':")
for f in arquivos_finais:
    print(f"  {f}")

print("\nAutomacao finalizada!")
driver.quit()
