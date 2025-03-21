# Shuffle SDK
This is the SDK used for app development, testing and production of ALL apps in Shuffle. Works with manual runs, Docker, k8s, cloud serverless. 

Released under [Python pip for usage outside of Shuffle](https://pypi.org/project/shuffle-sdk/) 

Python apps: [https://github.com/shuffle/python-apps](https://github.com/shuffle/python-apps)
All apps: [https://shuffler.io/search](https://shuffler.io/search)

## Usage with Shuffle
Refer to the [Shuffle App Creation docs](https://shuffler.io/docs/app_creation)

## Build
`docker build . -t shuffle/shuffle:app_sdk`

## Download
```
pip install shuffle_sdk
```

## Usage
```python
from shuffle_sdk import AppBase

class Example(AppBase):
    def sample_function(self, paramname):
        return f"Hello {paramname}"

if __name__ == "__main__":
    Example.run()
```

## Testing Shuffle Apps
With the above function as an example
```bash
python3 app.py --standalone --action=sample_function paramname=World
```

Example wit [Shuffle Tools+Liquid](https://github.com/Shuffle/python-apps/tree/master/shuffle-tools/1.2.0/src) and the [Shuffle Tools app and the "repeat back to me" function](https://github.com/Shuffle/python-apps/blob/678187d1198f5e8fd2072e475dbbbf858728dde8/shuffle-tools/1.2.0/src/app.py#L235)
```bash
python3 app.py --standalone --action=repeat_back_to_me '--call={{ "hello" | replace: "o", "lol" }}'
```

Example using [Shuffle Tools](https://github.com/Shuffle/python-apps/tree/master/shuffle-tools/1.2.0/src) [Shuffle actions](https://github.com/shuffle/shufflepy) within the "execute_python" function to get emails from Outlook ([app.py](https://github.com/Shuffle/python-apps/blob/678187d1198f5e8fd2072e475dbbbf858728dde8/shuffle-tools/1.2.0/src/app.py#L570))
```bash
python3 app.py --standalone --action=execute_python 'code=print(shuffle.run_app(app_id="accdaaf2eeba6a6ed43b2efc0112032d", action="get_emails"))'
```

Example [LLM inference with the Shuffle-AI app](https://github.com/Shuffle/python-apps/tree/master/shuffle-ai/1.0.0/src). Supports GPU and requires ollama installed and serving. 
```bash
python3 app.py --standalone --action=run_llm 'input=convert the following data into a python list of valid ips: 12.3.4.4'
```

If successful, the output of the function will show in your CLI.

## Testing functions inside Shuffle App images manually
This is mostly the same, but paths and docker is a part of the command.
```
docker run frikky/shuffle:shuffle-ai_1.0.0 python3 /app/app.py standalone --action=run_llm '--input=llm, please answer this question thanks'
```

With GPU's active in Docker for the LLM (requires [Nvidia Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)):
```
docker run --gpus all GPU_LAYERS=8 frikky/shuffle:shuffle-ai_1.0.0 python3 /app/app.py standalone --action=run_llm '--input=llm, please answer this question thanks'
```

## Building a fully functional Shuffle App
[Look at the documentation on our website](https://shuffler.io/docs/app_creation)

## Adding new [Liquid filters](https://shuffler.io/docs/liquid)
Add a function along these lines:
```
@shuffle_filters.register
def md5(a):
    a = str(a)
    return hashlib.md5(a.encode('utf-8')).hexdigest()
```

This can be used as `{{ "string" | md5 }}`, where `"string"` -> the `a` parameter of the function

## (Scale testing) Running the Shuffle Tools within the Shuffle Tools app locally
1. Set your env `SHUFFLE_APP_EXPOSED_PORT=8080` and `SHUFFLE_SWARM_CONFIG=run`
2. Run the [Shuffle Tools app](https://github.com/Shuffle/python-apps/tree/master/shuffle-tools/1.2.0/src) as a webserver: `python3 app.py`
3. Send a local request to the Shuffle Tools app to run an action within an action. **Make sure to add an authorization & execution_id that exists**
```
curl -XPOST http://localhost:8080/api/v1/run -H "Content-Type: application/json" -d '{
    "action": {"app_name": "shuffle tools", "name": "execute_python", "parameters": [{
        "name": "code", 
        "value": "singul.config[\"url\"] = \"https://shuffler.io\";print(singul.run_app(app_id=\"3e2bdf9d5069fe3f4746c29d68785a6a\", action=\"repeat_back_to_me\", parameters=[{\"name\": \"call\", \"value\": \"testing\"}]))"}]
    }, 
    "authorization": "",
    "execution_id": ""
}
'
```

You can replace the singul.config URL with a local instance for local testing as well.
