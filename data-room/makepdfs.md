# Quick Reference: Generate PDFs

This guide provides terminal commands to generate PDFs from markdown files on **Windows** and **macOS/Linux**.

---

## Prerequisites

Ensure you have **Node.js 18+** installed:

```bash
# Check Node.js version
node --version

# Should output: v18.x.x or higher
```

If Node.js is not installed:
- **Windows:** Download from [nodejs.org](https://nodejs.org)
- **macOS:** `brew install node`
- **Linux:** `sudo apt install nodejs npm` (or equivalent)

---

## Step 1: Install Dependencies

Open a terminal in the `data-room/` folder and run:

### Windows (Command Prompt)
```cmd
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\data-room
npm install
```

### Windows (PowerShell)
```powershell
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\data-room
npm install
```

### macOS/Linux (Bash/Zsh)
```bash
cd ~/Desktop/crypto_ai_bot/data-room
npm install
```

**This will install:**
- `md-to-pdf` (Markdown to PDF converter)
- `rimraf` (Cross-platform file deletion)
- `live-server` (Local preview server)

---

## Step 2: Generate PDFs

### Windows (Command Prompt or PowerShell)
```cmd
npm run build
```

### macOS/Linux (Bash/Zsh)
```bash
npm run build
```

**Output:**
```
═══════════════════════════════════════
  Crypto-AI-Bot Data Room PDF Builder
═══════════════════════════════════════

Found 6 markdown file(s)

  Converting: 250110_README_index.md...
  ✓ Generated: 250110_README_index.pdf
  Converting: 250110_metrics_signals_snapshot.md...
  ✓ Generated: 250110_metrics_signals_snapshot.pdf
  ...

═══════════════════════════════════════
  Build Summary
═══════════════════════════════════════

✓ Successful: 6
```

**PDFs will be saved to:** `data-room/out/`

---

## Step 3: View Generated PDFs

### Windows (File Explorer)
```cmd
start out
```

Or manually navigate to:
```
C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\data-room\out\
```

### macOS (Finder)
```bash
open out/
```

### Linux
```bash
xdg-open out/
```

---

## Additional Commands

### Clean Output Folder
Delete all generated PDFs:

```bash
npm run clean
```

### Preview PDFs in Browser
Start a local web server to preview PDFs:

```bash
npm run preview
```

Then open: http://localhost:8080

Press `Ctrl+C` to stop the server.

---

## Troubleshooting

### Issue: "npm: command not found"

**Cause:** Node.js is not installed or not in PATH

**Fix:**
1. Install Node.js from [nodejs.org](https://nodejs.org)
2. Restart terminal
3. Verify: `node --version`

---

### Issue: "Error: Failed to launch the browser process"

**Cause:** Puppeteer (used by md-to-pdf) requires Chromium

**Fix (Windows):**
```cmd
npm install puppeteer --save-dev
```

**Fix (macOS/Linux):**
```bash
npm install puppeteer --save-dev
```

If still failing, manually download Chromium:
```bash
node node_modules/puppeteer/install.js
```

---

### Issue: Images Not Showing in PDF

**Cause:** Image files missing from `_assets/` folder

**Fix:**
1. Add all screenshots to `_assets/` folder
2. Ensure markdown uses correct paths: `../_assets/image.png`
3. Rebuild: `npm run build`

---

### Issue: PDF Formatting Looks Wrong

**Cause:** Custom CSS may need adjustment

**Fix:**
1. Edit `print.css` to adjust margins, fonts, etc.
2. Rebuild: `npm run build`
3. Review output in `out/`

---

## Full Workflow Example

### Windows (PowerShell)
```powershell
# Navigate to data-room
cd C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\data-room

# Install dependencies (first time only)
npm install

# Add screenshots to _assets/ folder
# (Use Snipping Tool, Greenshot, etc.)

# Generate PDFs
npm run build

# View PDFs
start out\

# Clean up (if needed)
npm run clean
```

### macOS/Linux (Bash)
```bash
# Navigate to data-room
cd ~/Desktop/crypto_ai_bot/data-room

# Install dependencies (first time only)
npm install

# Add screenshots to _assets/ folder
# (Use Cmd+Shift+4 on macOS)

# Generate PDFs
npm run build

# View PDFs
open out/

# Clean up (if needed)
npm run clean
```

---

## What Gets Generated

After running `npm run build`, you'll have:

```
out/
├── 250110_README_index.pdf
├── 250110_metrics_signals_snapshot.pdf
├── 250110_metrics_ops_health.pdf
├── 250110_metrics_traffic_12mo.pdf
├── 250110_tech_stack_overview.pdf
└── 250110_why_im_selling.pdf
```

**Total:** 6 PDFs ready for distribution.

---

## Sharing PDFs

### Option 1: ZIP Archive

**Windows (PowerShell):**
```powershell
Compress-Archive -Path out -DestinationPath crypto-bot-data-room.zip
```

**macOS/Linux:**
```bash
zip -r crypto-bot-data-room.zip out/
```

### Option 2: Cloud Storage

Upload `out/` folder to:
- Google Drive
- Dropbox
- OneDrive
- WeTransfer (for large files)

---

## Customization

### Change Paper Size
Edit `scripts/build.mjs`, line ~85:
```javascript
format: 'A4',  // Change to 'Letter', 'Legal', etc.
```

### Change Margins
Edit `print.css`, line ~4:
```css
@page {
  margin: 20mm 15mm;  /* Top/Bottom Left/Right */
}
```

### Change Font
Edit `print.css`, line ~13:
```css
body {
  font-family: 'Arial', 'Helvetica', sans-serif;
}
```

After making changes, rebuild:
```bash
npm run build
```

---

## Help & Support

For issues with this build system, check:
1. `README.md` — Full documentation
2. `package.json` — Script definitions
3. `scripts/build.mjs` — Build script source

---

**End of Guide**
