# StockLens — Analýza burzovních firem

## Požadavky
- Python 3.9+
- Webový prohlížeč (Chrome, Firefox, Edge)

---

## Spuštění — 3 kroky

### 1. Nastav FMP API klíč
Otevři soubor `backend/.env` a vlož svůj klíč:
```
FMP_API_KEY=sem_vloz_svuj_klic
```

### 2. Spusť backend
Otevři terminál, přejdi do složky `backend/` a spusť:

```bash
cd backend

# Nainstaluj závislosti (jen poprvé)
pip install -r requirements.txt

# Spusť server
uvicorn main:app --reload
```

Backend poběží na: http://localhost:8000

### 3. Otevři frontend
Otevři soubor `frontend/index.html` přímo v prohlížeči
(dvojklik na soubor, nebo přetáhni do prohlížeče)

---

## Použití
- Zadej ticker (AAPL, MSFT, TSLA) nebo název firmy (Tesla, Apple)
- Aplikace zobrazí finanční přehled, grafy, výhled analytiků

## Zelený pruh = vše OK, červený = backend neběží nebo chybí API klíč

---

## Struktura projektu
```
stocklens/
├── backend/
│   ├── main.py          ← Python API server
│   ├── requirements.txt ← závislosti
│   └── .env             ← tvůj FMP API klíč (nezveřejňuj!)
└── frontend/
    └── index.html       ← aplikace v prohlížeči
```
