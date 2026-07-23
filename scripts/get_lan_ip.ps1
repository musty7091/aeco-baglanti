$ErrorActionPreference = 'SilentlyContinue'

$configs = Get-NetIPConfiguration | Where-Object {
    $_.NetAdapter.Status -eq 'Up' -and
    $_.IPv4Address -and
    $_.IPv4DefaultGateway -and
    $_.InterfaceAlias -notmatch 'Loopback|vEthernet|VirtualBox|VMware|Tailscale|WireGuard|Hyper-V|Bluetooth'
}

$candidates = foreach ($config in $configs) {
    $metric = (Get-NetIPInterface -InterfaceIndex $config.InterfaceIndex -AddressFamily IPv4).InterfaceMetric
    foreach ($address in $config.IPv4Address) {
        $ip = $address.IPAddress
        if ($ip -and $ip -notlike '127.*' -and $ip -notlike '169.254.*') {
            [pscustomobject]@{
                IP = $ip
                Metric = if ($null -eq $metric) { 9999 } else { [int]$metric }
                Alias = $config.InterfaceAlias
            }
        }
    }
}

$selected = $candidates | Sort-Object Metric | Select-Object -First 1

if (-not $selected) {
    $selected = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
        $_.IPAddress -notlike '127.*' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.InterfaceAlias -notmatch 'Loopback|vEthernet|VirtualBox|VMware|Tailscale|WireGuard|Hyper-V|Bluetooth'
    } | Select-Object -First 1 @{Name='IP';Expression={$_.IPAddress}}
}

if ($selected -and $selected.IP) {
    Write-Output $selected.IP
}
