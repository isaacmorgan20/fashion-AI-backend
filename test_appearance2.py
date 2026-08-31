import requests, json
url='https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=AIzaSyBPvgPEN8916bKwMzlz1_NR487NFijAApo'
resp=requests.post(url, json={'email':'test@example.com','password':'testpassword123','returnSecureToken':True})
tok=resp.json().get('idToken')
h={'Authorization': f'Bearer {tok}'}
for theme in ['light','dark','system']:
    r=requests.patch('http://127.0.0.1:8000/api/v1/settings', headers=h, json={'appearance':{'theme':theme}})
    print(f'PATCH theme {theme}', r.json().get('appearance'))
    r2=requests.get('http://127.0.0.1:8000/api/v1/settings', headers=h)
    print(f"  GET {r2.json().get('appearance',{}).get('theme')}")
for compact in [True, False]:
    r=requests.patch('http://127.0.0.1:8000/api/v1/settings', headers=h, json={'appearance':{'compact':compact}})
    print(f'PATCH compact {compact}', r.json().get('appearance'))
    r2=requests.get('http://127.0.0.1:8000/api/v1/settings', headers=h)
    print(f"  GET compact {r2.json().get('appearance',{}).get('compact')}")
requests.patch('http://127.0.0.1:8000/api/v1/settings', headers=h, json={'appearance':{'theme':'system','compact':False}})
print('reset done')
