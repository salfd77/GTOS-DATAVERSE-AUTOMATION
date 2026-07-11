# provision_with_pac.ps1
# Alternative provisioning path using the Microsoft Power Platform CLI (pac)
# plus the Python script. Use this on Windows/WSL2 if you prefer pac auth.
#
# Prereqs:
#   - Install Power Platform CLI:  https://aka.ms/PowerPlatformCLI
#   - Python 3.9+ available on PATH
#
# What it does:
#   1. Authenticates pac to your environment (interactive).
#   2. (Optional) creates an unmanaged solution + publisher for the gtos_ prefix.
#   3. Runs the Python provisioning script to create tables/columns.
#
# Note: table/column creation itself is done by provision_gtos_dataverse.py via
# the Dataverse Web API. pac here is used only for auth/solution scaffolding.

param(
    [Parameter(Mandatory = $true)] [string] $EnvironmentUrl,
    [string] $SolutionName = "",
    [string] $PublisherPrefix = "gtos",
    [switch] $WhatIf
)

Write-Host "== GTOS Dataverse provisioning (pac + python) ==" -ForegroundColor Cyan

# 1) Auth
Write-Host "Authenticating pac to $EnvironmentUrl ..." -ForegroundColor Yellow
pac auth create --url $EnvironmentUrl

# 2) Optional solution + publisher scaffolding
if ($SolutionName -ne "") {
    Write-Host "Ensuring publisher '$PublisherPrefix' and solution '$SolutionName' ..." -ForegroundColor Yellow
    pac solution init --publisher-name $PublisherPrefix --publisher-prefix $PublisherPrefix 2>$null
    # If the solution does not exist yet, create it in the environment:
    # pac solution create-settings ...  (adjust per your pac version)
}

# 3) Run the Python provisioner
$py = "provision_gtos_dataverse.py"
if ($WhatIf) {
    Write-Host "Running dry run (no changes) ..." -ForegroundColor Yellow
    python $py --whatif
} else {
    Write-Host "Creating tables and columns ..." -ForegroundColor Yellow
    python $py
}

Write-Host "Done." -ForegroundColor Green
