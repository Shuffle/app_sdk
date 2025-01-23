# Shuffle SDK
This is the SDK used for app development, testing and production of ALL apps in Shuffle. Works with manual runs, Docker, k8s, cloud serverless. 

Released under [Python pip for usage outside of Shuffle](https://pypi.org/project/shuffle-sdk/) 

Python apps: [https://github.com/shuffle/python-apps](https://github.com/shuffle/python-apps)
All apps: [https://shuffler.io/search](https://shuffler.io/search)

## Usage
Refer to the [Shuffle App Creation docs](https://shuffler.io/docs/app_creation)

**It is NOT meant to be used standalone with python scripts _yet_. This is a coming feature. **

## Build
`docker build . -t shuffle/shuffle:app_sdk`

## Download
```
pip install shuffle_sdk
```

## Usage
```
import shuffle_sdk
```

## Adding new [Liquid filters](https://shuffler.io/docs/liquid)
Add a function along these lines:
```
@shuffle_filters.register
def md5(a):
    a = str(a)
    return hashlib.md5(a.encode('utf-8')).hexdigest()
```

This can be used as `{{ "string" | md5 }}`, where `"string"` -> the `a` parameter of the function
