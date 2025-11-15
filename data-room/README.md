# Data Room — Crypto-AI-Bot SaaS Platform

This data room contains comprehensive documentation for potential buyers of the Crypto-AI-Bot SaaS platform.

---

## Structure

```
data-room/
├── 01_Metrics/              # Performance and analytics reports
├── 02_Product_Demo/         # Screenshots and demo materials
├── 03_Tech_Stack/           # Technical architecture docs
├── 04_Financials/           # Revenue, costs, profitability
├── 05_Operations_SOPs/      # Deployment and maintenance guides
├── 06_Transition_Plan/      # Handover timeline and checklist
├── 07_Buyer_FAQ/            # Frequently asked questions
├── _assets/                 # Screenshots and images (PNG format)
├── docs/                    # Source markdown files
├── out/                     # Generated PDFs (after build)
├── scripts/                 # Build automation
├── README.md                # This file
├── makepdfs.md              # Commands to generate PDFs
├── package.json             # Node.js dependencies
└── print.css                # PDF styling
```

---

## Quick Start

### 1. Add Screenshots

Place all screenshot images in the `_assets/` folder:

```bash
_assets/
├── 250110_strategy_attribution.png
├── 250110_paper_performance_30d.png
├── 250110_data_pipeline_diagram.png
├── 250110_grafana_dashboard.png
├── 250110_infra_diagram.png
├── 250110_api_latency_p95.png
├── 250110_redis_memory_usage.png
├── 250110_prometheus_overview.png
├── 250110_api_throughput_graph.png
├── 250110_traffic_monthly_volume.png
├── 250110_traffic_hourly_pattern.png
├── 250110_signal_consumption_rate.png
├── 250110_api_latency_12mo.png
├── 250110_traffic_forecast_2025.png
└── 250110_architecture_diagram.png
```

**Recommended Tools:**
- Windows: Snipping Tool, Greenshot
- macOS: Cmd+Shift+4
- Grafana: Use "Share → Export" for dashboards

---

### 2. Install Dependencies

Install Node.js dependencies for PDF generation:

```bash
# Navigate to data-room folder
cd data-room

# Install dependencies
npm install
```

**Dependencies:**
- `md-to-pdf` — Markdown to PDF converter (uses Puppeteer)
- `rimraf` — Cross-platform file deletion
- `live-server` — Local preview server

---

### 3. Generate PDFs

Build all PDFs from markdown files:

```bash
npm run build
```

This will:
- Read all `.md` files from `docs/`
- Generate PDFs in `out/` folder
- Apply `print.css` styling (A4 size, margins, page numbers)

**Output:**
```
out/
├── 250110_README_index.pdf
├── 250110_metrics_signals_snapshot.pdf
├── 250110_metrics_ops_health.pdf
├── 250110_metrics_traffic_12mo.pdf
├── 250110_tech_stack_overview.pdf
└── 250110_why_im_selling.pdf
```

---

### 4. Preview PDFs

Open PDFs locally:

```bash
# Windows
start out\

# macOS/Linux
open out/

# Or use live-server for quick preview
npm run preview
```

---

## Build Commands Reference

| Command          | Description                          |
|------------------|--------------------------------------|
| `npm run build`  | Generate all PDFs from markdown      |
| `npm run clean`  | Delete `out/` folder                 |
| `npm run preview`| Start local server to view PDFs      |

---

## Markdown Conventions

All markdown files in `docs/` follow these conventions:

1. **File Naming:** `YYMMDD_description.md` (e.g., `250110_tech_stack_overview.md`)
2. **Front Matter:** Title, date, and summary at the top
3. **Image References:** Use relative paths (e.g., `../_assets/image.png`)
4. **Print-Ready:** Clean formatting, no excessive nesting, clear headings

---

## Customizing PDFs

### Print Stylesheet

Edit `print.css` to customize PDF appearance:

```css
/* Example: Change margins */
@page {
  margin: 20mm 15mm;
}

/* Example: Change font size */
body {
  font-size: 11pt;
}
```

### PDF Metadata

Edit `scripts/build.mjs` to customize PDF metadata:

```javascript
pdf_options: {
  format: 'A4',           // Paper size
  margin: '20mm',         // Margins
  displayHeaderFooter: true,
  headerTemplate: '...',
  footerTemplate: '...'
}
```

---

## Troubleshooting

### Issue: Images Not Showing in PDF

**Cause:** Image file paths are incorrect or images missing from `_assets/`

**Fix:**
1. Ensure all images are in `_assets/` folder
2. Check markdown uses correct relative path: `../_assets/image.png`
3. Rebuild: `npm run build`

---

### Issue: PDF Generation Fails on Windows

**Cause:** Puppeteer (used by md-to-pdf) may need additional setup on Windows

**Fix:**
1. Ensure Node.js 18+ is installed
2. Run: `npm install --save-dev puppeteer`
3. If still failing, try: `set PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=false && npm install`

---

### Issue: Fonts Look Wrong in PDF

**Cause:** System fonts may differ between preview and PDF

**Fix:**
1. Edit `print.css` to specify web-safe fonts:
   ```css
   body {
     font-family: 'Arial', 'Helvetica', sans-serif;
   }
   ```
2. Rebuild: `npm run build`

---

## Adding New Documents

To add a new markdown document:

1. Create `docs/250110_new_document.md`
2. Follow naming convention: `YYMMDD_description.md`
3. Include title, date, and summary at top
4. Use relative image paths: `../_assets/`
5. Run `npm run build` to generate PDF

**Note:** The build script automatically processes all `.md` files in `docs/`, no configuration needed.

---

## Sharing the Data Room

### Option 1: PDF Bundle (Recommended)

Send the `out/` folder as a ZIP file:

```bash
# Windows (PowerShell)
Compress-Archive -Path out -DestinationPath crypto-bot-data-room.zip

# macOS/Linux
zip -r crypto-bot-data-room.zip out/
```

### Option 2: GitHub Private Repo

Push to a private repo and grant buyer access:

```bash
git init
git add .
git commit -m "Initial data room"
git remote add origin https://github.com/yourusername/crypto-bot-data-room.git
git push -u origin main
```

### Option 3: Google Drive / Dropbox

Upload the entire `data-room/` folder to cloud storage and share link.

---

## Updating Documentation

To update existing docs:

1. Edit markdown files in `docs/`
2. Add/replace images in `_assets/`
3. Rebuild: `npm run build`
4. Review PDFs in `out/`

---

## License

This data room and all contents are confidential and intended solely for prospective buyers of the Crypto-AI-Bot platform. Do not share or distribute without permission.

---

## Questions?

For questions about this data room or the acquisition, contact the seller directly (see `250110_why_im_selling.md` for contact info).
