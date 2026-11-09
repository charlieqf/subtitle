param(
    [string]$CredentialFile = (Join-Path $PSScriptRoot '.private\provider-credentials.env')
)
$ErrorActionPreference = 'Stop'
$allowed = @(
    'TENCENT_APP_ID', 'TENCENT_SECRET_ID', 'TENCENT_SECRET_KEY',
    'DASHSCOPE_API_KEY', 'ALIYUN_WORKSPACE_ID',
    'ALIYUN_ASR_BASE_URL', 'ALIYUN_WORKSPACE_BASE_URL'
)
$entries = @{}
foreach ($line in [IO.File]::ReadAllLines($CredentialFile, [Text.Encoding]::UTF8)) {
    if ($line -match '^([A-Z][A-Z0-9_]+)=(.*)$' -and $allowed -contains $Matches[1]) {
        $entries[$Matches[1]] = $Matches[2]
    }
}
foreach ($required in @('TENCENT_APP_ID', 'TENCENT_SECRET_ID', 'TENCENT_SECRET_KEY', 'DASHSCOPE_API_KEY')) {
    if ([string]::IsNullOrWhiteSpace($entries[$required])) { throw "Required field missing: $required" }
}
foreach ($entry in $entries.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
}
Write-Output 'Provider credentials loaded into this process. Values are not displayed.'
