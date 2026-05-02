/**
 * Script para conectar Google Sheets con tu Agente Manager.
 * 
 * INSTRUCCIONES:
 * 1. En tu Google Sheet (ventas2026), ve a: Extensiones > Apps Script.
 * 2. Borra todo el código y pega este archivo.
 * 3. Haz clic en "Implementar" > "Nueva implementación".
 * 4. Selecciona tipo: "Aplicación Web".
 * 5. Ejecutar como: "Tú".
 * 6. Quién tiene acceso: "Cualquier persona" (importante para que el bot pueda leerlo).
 * 7. Copia la "URL de la aplicación web" y ponla en tu .env como GOOGLE_SCRIPT_URL.
 */

function doGet(e) {
  var sheetName = e.parameter.sheet || "ventas2026"; // Por defecto usa la hoja de ventas
  var filterVisitador = e.parameter.visitador;
  
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(sheetName);
  
  if (!sheet) {
    return ContentService.createTextOutput(JSON.stringify({
      "ok": false, 
      "error": "Hoja no encontrada: " + sheetName
    })).setMimeType(ContentService.MimeType.JSON);
  }
  
  var data = sheet.getDataRange().getValues();
  var headers = data[0];
  var rows = data.slice(1);
  
  var records = rows.map(function(row) {
    var obj = {};
    headers.forEach(function(header, i) {
      obj[header.toString().toLowerCase().replace(/ /g, "_")] = row[i];
    });
    return obj;
  });
  
  // Filtrar si se solicita
  if (filterVisitador) {
    records = records.filter(function(r) {
      var nombre = r.nombre_visitador || r.visitador || r.nombre || "";
      return nombre.toString().toLowerCase().indexOf(filterVisitador.toLowerCase()) !== -1;
    });
  }
  
  return ContentService.createTextOutput(JSON.stringify({
    "ok": true,
    "records": records
  })).setMimeType(ContentService.MimeType.JSON);
}
