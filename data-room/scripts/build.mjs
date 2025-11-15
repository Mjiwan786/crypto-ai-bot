#!/usr/bin/env node

/**
 * Build Script: MD → PDF Conversion
 *
 * Reads all .md files from docs/ and generates PDFs in out/
 * Uses md-to-pdf with print.css for styling
 *
 * Usage: node scripts/build.mjs
 */

import { mdToPdf } from 'md-to-pdf';
import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

// Get current directory (ESM workaround)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.join(__dirname, '..');

// Directories
const docsDir = path.join(rootDir, 'docs');
const outDir = path.join(rootDir, 'out');
const cssPath = path.join(rootDir, 'print.css');

// Colors for terminal output
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
};

/**
 * Log with color
 */
function log(message, color = colors.reset) {
  console.log(`${color}${message}${colors.reset}`);
}

/**
 * Ensure output directory exists
 */
async function ensureOutDir() {
  try {
    await fs.access(outDir);
  } catch {
    await fs.mkdir(outDir, { recursive: true });
    log(`✓ Created output directory: ${outDir}`, colors.green);
  }
}

/**
 * Get all .md files from docs/
 */
async function getMarkdownFiles() {
  try {
    const files = await fs.readdir(docsDir);
    return files.filter(file => file.endsWith('.md'));
  } catch (error) {
    log(`✗ Error reading docs directory: ${error.message}`, colors.red);
    process.exit(1);
  }
}

/**
 * Convert a single markdown file to PDF
 */
async function convertToPdf(filename) {
  const inputPath = path.join(docsDir, filename);
  const outputFilename = filename.replace('.md', '.pdf');
  const outputPath = path.join(outDir, outputFilename);

  try {
    log(`  Converting: ${filename}...`, colors.cyan);

    const pdf = await mdToPdf(
      { path: inputPath },
      {
        dest: outputPath,
        pdf_options: {
          format: 'A4',
          margin: {
            top: '20mm',
            right: '15mm',
            bottom: '20mm',
            left: '15mm',
          },
          displayHeaderFooter: true,
          headerTemplate: '<div></div>',
          footerTemplate: `
            <div style="font-size: 9px; color: #666; width: 100%; text-align: center; padding: 5px 0;">
              <span class="pageNumber"></span> / <span class="totalPages"></span>
            </div>
          `,
          printBackground: true,
        },
        stylesheet: [cssPath],
        basedir: rootDir,
      }
    );

    log(`  ✓ Generated: ${outputFilename}`, colors.green);
    return { success: true, filename };
  } catch (error) {
    log(`  ✗ Failed: ${filename} - ${error.message}`, colors.red);
    return { success: false, filename, error: error.message };
  }
}

/**
 * Main build function
 */
async function build() {
  console.log();
  log('═══════════════════════════════════════', colors.blue);
  log('  Crypto-AI-Bot Data Room PDF Builder', colors.blue);
  log('═══════════════════════════════════════', colors.blue);
  console.log();

  // Ensure output directory exists
  await ensureOutDir();

  // Get all markdown files
  const markdownFiles = await getMarkdownFiles();

  if (markdownFiles.length === 0) {
    log('✗ No markdown files found in docs/', colors.yellow);
    process.exit(0);
  }

  log(`Found ${markdownFiles.length} markdown file(s)`, colors.blue);
  console.log();

  // Convert all files
  const results = [];
  for (const file of markdownFiles) {
    const result = await convertToPdf(file);
    results.push(result);
  }

  // Summary
  console.log();
  log('═══════════════════════════════════════', colors.blue);
  log('  Build Summary', colors.blue);
  log('═══════════════════════════════════════', colors.blue);
  console.log();

  const successful = results.filter(r => r.success).length;
  const failed = results.filter(r => !r.success).length;

  log(`✓ Successful: ${successful}`, colors.green);
  if (failed > 0) {
    log(`✗ Failed: ${failed}`, colors.red);
    console.log();
    log('Failed files:', colors.yellow);
    results.filter(r => !r.success).forEach(r => {
      log(`  - ${r.filename}: ${r.error}`, colors.red);
    });
  }

  console.log();
  log(`Output directory: ${outDir}`, colors.cyan);
  console.log();

  // Exit with error code if any failed
  process.exit(failed > 0 ? 1 : 0);
}

// Run build
build().catch(error => {
  log(`✗ Build failed: ${error.message}`, colors.red);
  console.error(error);
  process.exit(1);
});
