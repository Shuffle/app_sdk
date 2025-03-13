from setuptools import setup, find_packages

setup(
    name='shuffle_sdk',  
    version='0.0.17',  
    description='The SDK used for Shuffle',  
    py_modules=["shuffle_sdk"],  
    license='MIT',
    long_description=open('README.md').read(),  
    long_description_content_type='text/markdown',  
    author='Fredrik Saito Odegaardstuen',  
    author_email='frikky@shuffler.io',  
    url='https://github.com/shuffle/shuffle',  
    packages=find_packages(),  
    install_requires=[
        "urllib3==2.3.0",
        "requests==2.32.3",
        "MarkupSafe==3.0.2",
        "liquidpy==0.8.2",
        "flask[async]==3.1.0",
        "waitress==3.0.2",
        "python-dateutil==2.9.0.post0",
        "PyJWT==2.10.1",
        "shufflepy==0.0.7",
    ],
    classifiers=[  
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.7',  # Specify Python version requirements
)
