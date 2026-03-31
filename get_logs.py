import requests
import sys

API_KEY = "rnd_giz1w5LQ0tFKcjP3eaJALG7UV7M9"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json"
}

res = requests.get("https://api.render.com/v1/services", headers=HEADERS)
if not res.ok:
    print("Failed to get services:", res.text)
    sys.exit(1)

services = res.json()
if not services:
    print("No services found.")
    sys.exit(0)

service_id = services[0]['service']['id']
print(f"Service ID: {service_id}")

deploys_res = requests.get(f"https://api.render.com/v1/services/{service_id}/deploys", headers=HEADERS)
deploys = deploys_res.json()

for deploy in deploys:
    d = deploy['deploy']
    if d['status'] in ('failed', 'canceled', 'live', 'build_failed', 'update_failed'):
        print(f"Latest relevant deploy: {d['id']} - Status: {d['status']}")
        if d.get('statusDetail'):
            print(f"Status Detail: {d['statusDetail']}")
        break
