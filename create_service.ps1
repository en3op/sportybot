$headers = @{
    'Authorization' = 'Bearer rnd_giz1w5LQ0tFKcjP3eaJALG7UV7M9'
    'Accept'        = 'application/json'
    'Content-Type'  = 'application/json'
}

$bodyObj = @{
    type           = 'web_service'
    name           = 'sportybot-v2'
    repo           = 'https://github.com/en3op/sportybot'
    branch         = 'master'
    ownerId        = 'tea-d6aqakbnv86c739s5k50'
    serviceDetails = @{
        env            = 'docker'
        plan           = 'free'
        region         = 'oregon'
        dockerContext  = '.'
        dockerfilePath = 'Dockerfile'
    }
    envVars        = @(
        @{ key = 'FREE_BOT_TOKEN'; value = '8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw' }
        @{ key = 'VIP_BOT_TOKEN'; value = '8791071506:AAGZv4Y3GWSMQ5mnj_vH2cT3p0BWEpxOOmk' }
        @{ key = 'API_FOOTBALL_KEY'; value = '932929ad49d522381384d69aec31fc99' }
        @{ key = 'PORT'; value = '5000' }
    )
}

$body = $bodyObj | ConvertTo-Json -Depth 5

try {
    $response = Invoke-RestMethod -Method Post -Uri 'https://api.render.com/v1/services' -Headers $headers -Body $body
    $response | ConvertTo-Json -Depth 5
} catch {
    Write-Error $_
    $_.Exception.Response.GetResponseStream() | ForEach-Object { (New-Object System.IO.StreamReader($_)).ReadToEnd() }
}
