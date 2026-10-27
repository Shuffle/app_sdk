from setuptools import setup, find_packages

setup(
    name='shuffle_sdk',  
    version='0.0.42',
    description='The SDK used for Shuffle',  
    py_modules=["shuffle_sdk"],  
    license='MIT',
    long_description=open('README.md').read(),  
    long_description_content_type='text/markdown',  
    author='Fredrik Saito Odegaardstuen',  
    author_email='frikky@shuffler.io',  
    url='https://github.com/shuffle/shuffle',  
    packages=find_packages(exclude=["tests", "tests.*"]),  
    install_requires=[
        "urllib3==2.8.0",
        "requests==2.34.2",
        "MarkupSafe==3.0.4",
        "liquidpy==0.8.6",
        "flask[async]==3.1.3",
        "waitress==3.0.2",
        "python-dateutil==2.9.0.post0",
        "PyJWT==2.15.1",
        "shufflepy==0.2.2",
    ],
    classifiers=[  
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.10',  # Specify Python version requirements
)
