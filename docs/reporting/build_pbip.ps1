<#
  build_pbip.ps1  -  Generate a Power BI Project (PBIP) for GTOS from the exported CSVs.

  Reads the six gtos_*.csv files produced by verify_gtos_data.py and writes a PBIP
  semantic model (TMDL) that wires:
    - one table per CSV (all columns as text, refresh-safe),
    - the five GTOS relationships (name-based, since lookup values are display labels),
    - a "GTOS Measures" table with ready measures,
    - a FolderPath parameter pointing at your CSV folder.

  Open the generated GTOS.PBIP in Power BI Desktop (PBIP is on by default since 2024),
  then just drag fields onto pages. If your Desktop build cannot open PBIP, fall back to
  docs/reporting/powerbi-desktop-from-csv.md (fully manual, guaranteed).

  Usage:
    pwsh ./build_pbip.ps1
    pwsh ./build_pbip.ps1 -ExportFolder .\reporting_export -OutDir .\GTOS.PBIP
#>
param(
  [string]$ExportFolder = ".\reporting_export",
  [string]$OutDir       = ".\GTOS.PBIP",
  [string]$Name         = "GTOS"
)
$ErrorActionPreference = "Stop"
$TAB = "`t"

function New-Guid2 { [guid]::NewGuid().ToString() }
function Write-Text([string]$Path, [string]$Text) {
  $dir = Split-Path -Parent $Path
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  # UTF-8 without BOM, LF newlines
  $Text = $Text -replace "`r`n", "`n"
  [System.IO.File]::WriteAllText((Resolve-Path -LiteralPath $dir).Path + [IO.Path]::DirectorySeparatorChar + (Split-Path -Leaf $Path), $Text, (New-Object System.Text.UTF8Encoding($false)))
}

# Fixed GTOS relationship map: child, fromCol, parent, toCol, active
$RELS = @(
  @{ child="gtos_transformations"; from="_gtos_inputstate_value";   parent="gtos_states";          to="gtos_name"; active=$true  },
  @{ child="gtos_transformations"; from="_gtos_outputstate_value";  parent="gtos_states";          to="gtos_name"; active=$false },
  @{ child="gtos_findings";        from="_gtos_transformation_value";parent="gtos_transformations"; to="gtos_name"; active=$true  },
  @{ child="gtos_audits";          from="_gtos_governance_value";   parent="gtos_governances";     to="gtos_name"; active=$true  },
  @{ child="gtos_knowledges";      from="_gtos_relatedstate_value"; parent="gtos_states";          to="gtos_name"; active=$true  }
)

$MEASURES = @(
  @("Total Findings",            "COUNTROWS('gtos_findings')"),
  @("Open Findings",             "CALCULATE(COUNTROWS('gtos_findings'), 'gtos_findings'[gtos_accepted] = ""No"")"),
  @("Blocker Findings",          "CALCULATE(COUNTROWS('gtos_findings'), 'gtos_findings'[gtos_severity] = ""Blocker"")"),
  @("Major Findings",            "CALCULATE(COUNTROWS('gtos_findings'), 'gtos_findings'[gtos_severity] = ""Major"")"),
  @("Minor Findings",            "CALCULATE(COUNTROWS('gtos_findings'), 'gtos_findings'[gtos_severity] = ""Minor"")"),
  @("Total Transformations",     "COUNTROWS('gtos_transformations')"),
  @("Verified Transformations",  "CALCULATE(COUNTROWS('gtos_transformations'), 'gtos_transformations'[gtos_status] = ""Verified"")"),
  @("Transformation Coverage %", "DIVIDE([Verified Transformations], [Total Transformations])"),
  @("Total States",              "COUNTROWS('gtos_states')"),
  @("Active States",             "CALCULATE(COUNTROWS('gtos_states'), 'gtos_states'[gtos_status] = ""Active"")"),
  @("Total Audits",              "COUNTROWS('gtos_audits')")
)

if (-not (Test-Path $ExportFolder)) { throw "Export folder not found: $ExportFolder (run verify_gtos_data.py first)." }
$absExport = (Resolve-Path -LiteralPath $ExportFolder).Path
if (-not $absExport.EndsWith([IO.Path]::DirectorySeparatorChar)) { $absExport += [IO.Path]::DirectorySeparatorChar }

# Discover tables + headers from the CSVs.
$tables = [ordered]@{}
Get-ChildItem -Path $ExportFolder -Filter "gtos_*.csv" | Sort-Object Name | ForEach-Object {
  $tname = [IO.Path]::GetFileNameWithoutExtension($_.Name)
  $first = (Get-Content -LiteralPath $_.FullName -TotalCount 1) -replace "^\uFEFF", ""
  $cols  = $first.Split(",")
  $tables[$tname] = $cols
}
if ($tables.Count -eq 0) { throw "No gtos_*.csv files in $ExportFolder." }

$sm   = Join-Path $OutDir "$Name.SemanticModel"
$defn = Join-Path $sm "definition"

# --- .pbip ---
Write-Text (Join-Path $OutDir "$Name.pbip") @"
{
  "`$schema": "https://developer.microsoft.com/json-schemas/fabric/item/pbip/definitionProperties/1.0.0/schema.json",
  "version": "1.0",
  "artifacts": [ { "report": { "path": "$Name.Report" } } ],
  "settings": { "enableAutoRecovery": true }
}
"@

# --- SemanticModel/.platform ---
Write-Text (Join-Path $sm ".platform") @"
{
  "`$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
  "metadata": { "type": "SemanticModel", "displayName": "$Name" },
  "config": { "version": "2.0", "logicalId": "$(New-Guid2)" }
}
"@

Write-Text (Join-Path $sm "definition.pbism") "{`n  `"version`": `"4.2`",`n  `"settings`": {}`n}`n"

# --- database.tmdl ---
Write-Text (Join-Path $defn "database.tmdl") "database`n${TAB}compatibilityLevel: 1567`n"

# --- expressions.tmdl (FolderPath parameter, prefilled to your CSV folder) ---
$folderEsc = $absExport -replace "\\", "\\"
Write-Text (Join-Path $defn "expressions.tmdl") @"
expression FolderPath = "$folderEsc" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]
${TAB}lineageTag: $(New-Guid2)

${TAB}annotation PBI_ResultType = Text
"@

# --- tables ---
function Table-Tmdl([string]$tname, [string[]]$cols) {
  $sb = New-Object System.Text.StringBuilder
  [void]$sb.AppendLine("table $tname")
  [void]$sb.AppendLine("${TAB}lineageTag: $(New-Guid2)")
  [void]$sb.AppendLine("")
  foreach ($c in $cols) {
    [void]$sb.AppendLine("${TAB}column $c")
    [void]$sb.AppendLine("${TAB}${TAB}dataType: string")
    [void]$sb.AppendLine("${TAB}${TAB}lineageTag: $(New-Guid2)")
    [void]$sb.AppendLine("${TAB}${TAB}summarizeBy: none")
    [void]$sb.AppendLine("${TAB}${TAB}sourceColumn: $c")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("${TAB}${TAB}annotation SummarizationSetBy = Automatic")
    [void]$sb.AppendLine("")
  }
  [void]$sb.AppendLine("${TAB}partition $tname = m")
  [void]$sb.AppendLine("${TAB}${TAB}mode: import")
  [void]$sb.AppendLine("${TAB}${TAB}source =")
  [void]$sb.AppendLine("${TAB}${TAB}${TAB}let")
  [void]$sb.AppendLine("${TAB}${TAB}${TAB}    Source = Csv.Document(File.Contents(FolderPath & ""$tname.csv""), [Delimiter="","", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),")
  [void]$sb.AppendLine("${TAB}${TAB}${TAB}    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true])")
  [void]$sb.AppendLine("${TAB}${TAB}${TAB}in")
  [void]$sb.AppendLine("${TAB}${TAB}${TAB}    Promoted")
  [void]$sb.AppendLine("")
  return $sb.ToString()
}
foreach ($t in $tables.Keys) {
  Write-Text (Join-Path $defn "tables\$t.tmdl") (Table-Tmdl $t $tables[$t])
}

# --- measures table ---
$mb = New-Object System.Text.StringBuilder
[void]$mb.AppendLine("table 'GTOS Measures'")
[void]$mb.AppendLine("${TAB}lineageTag: $(New-Guid2)")
[void]$mb.AppendLine("")
foreach ($m in $MEASURES) {
  [void]$mb.AppendLine("${TAB}measure '$($m[0])' = $($m[1])")
  [void]$mb.AppendLine("${TAB}${TAB}lineageTag: $(New-Guid2)")
  [void]$mb.AppendLine("")
}
[void]$mb.AppendLine("${TAB}column Value")
[void]$mb.AppendLine("${TAB}${TAB}isHidden")
[void]$mb.AppendLine("${TAB}${TAB}dataType: int64")
[void]$mb.AppendLine("${TAB}${TAB}lineageTag: $(New-Guid2)")
[void]$mb.AppendLine("${TAB}${TAB}summarizeBy: none")
[void]$mb.AppendLine("${TAB}${TAB}sourceColumn: [Value]")
[void]$mb.AppendLine("")
[void]$mb.AppendLine("${TAB}partition 'GTOS Measures' = calculated")
[void]$mb.AppendLine("${TAB}${TAB}mode: import")
[void]$mb.AppendLine("${TAB}${TAB}source = {BLANK()}")
[void]$mb.AppendLine("")
Write-Text (Join-Path $defn "tables\GTOS Measures.tmdl") $mb.ToString()

# --- relationships.tmdl ---
$rb = New-Object System.Text.StringBuilder
foreach ($r in $RELS) {
  if (-not $tables.Contains($r.child) -or -not $tables.Contains($r.parent)) { continue }
  [void]$rb.AppendLine("relationship $(New-Guid2)")
  if (-not $r.active) { [void]$rb.AppendLine("${TAB}isActive: false") }
  [void]$rb.AppendLine("${TAB}fromColumn: $($r.child).$($r.from)")
  [void]$rb.AppendLine("${TAB}toColumn: $($r.parent).$($r.to)")
  [void]$rb.AppendLine("")
}
Write-Text (Join-Path $defn "relationships.tmdl") $rb.ToString()

# --- model.tmdl ---
$mo = New-Object System.Text.StringBuilder
[void]$mo.AppendLine("model Model")
[void]$mo.AppendLine("${TAB}culture: en-US")
[void]$mo.AppendLine("${TAB}defaultPowerBIDataSourceVersion: powerBI_V3")
[void]$mo.AppendLine("${TAB}sourceQueryCulture: en-US")
[void]$mo.AppendLine("${TAB}dataAccessOptions")
[void]$mo.AppendLine("${TAB}${TAB}legacyRedirects")
[void]$mo.AppendLine("${TAB}${TAB}returnErrorValuesAsNull")
[void]$mo.AppendLine("")
foreach ($t in $tables.Keys) { [void]$mo.AppendLine("${TAB}ref table $t") }
[void]$mo.AppendLine("${TAB}ref table 'GTOS Measures'")
[void]$mo.AppendLine("${TAB}ref cultureInfo en-US")
[void]$mo.AppendLine("")
Write-Text (Join-Path $defn "model.tmdl") $mo.ToString()

# --- Report stub ---
$rep = Join-Path $OutDir "$Name.Report"
Write-Text (Join-Path $rep ".platform") @"
{
  "`$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
  "metadata": { "type": "Report", "displayName": "$Name" },
  "config": { "version": "2.0", "logicalId": "$(New-Guid2)" }
}
"@
Write-Text (Join-Path $rep "definition.pbir") @"
{
  "version": "4.0",
  "datasetReference": { "byPath": { "path": "../$Name.SemanticModel" } }
}
"@

Write-Host ""
Write-Host "==== PBIP generated ===="
Write-Host ("Tables:        " + (($tables.Keys) -join ", "))
Write-Host ("Relationships: " + (@($RELS | Where-Object { $tables.Contains($_.child) -and $tables.Contains($_.parent) }).Count))
Write-Host ("CSV folder:    " + $absExport)
Write-Host ("Open:          " + (Join-Path $OutDir "$Name.pbip") + "  in Power BI Desktop")
Write-Host "Then drag fields onto pages (Findings / Audit / State / Transformation)."
Write-Host "If Desktop cannot open PBIP, use docs/reporting/powerbi-desktop-from-csv.md."
