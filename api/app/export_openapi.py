from .main import app
from threading import Thread
import uvicorn
import requests
from time import sleep

PORT = 33833
API_ENDPOINT = f'http://localhost:{PORT}/api/v1'

def run_api():
    uvicorn.run(app, host='0.0.0.0', port=PORT)

def wait_for_api_to_be_up():
    for _ in range(30):
        try:
            resp = requests.get(API_ENDPOINT)
            if resp.status_code == 200:
                return
        except:
            pass
        sleep(1)
    raise Exception('API did not start up in time')      

def get_openapi_json():
    resp = requests.get(f'{API_ENDPOINT}/openapi.json')
    if resp.status_code != 200:
        raise Exception('Could not download openapi.json')
    return resp.text    

print('Starting API')
api_thread = Thread(target=run_api, daemon=True)
api_thread.start()

wait_for_api_to_be_up()
print('API is up')

with open('openapi.json', 'w') as f:
    f.write(get_openapi_json())
print('Dumped openapi.json')