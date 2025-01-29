from setuptools import setup, find_packages

def parse_requirements(filename):
    """Load requirements from a requirements.txt file."""
    with open(filename) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name='shuffle_sdk',  
    version='0.0.',  
    description='The SDK used for Shuffle',  
    py_modules=["shuffle_sdk"],  
    license='MIT',
    long_description=open('README.md').read(),  
    long_description_content_type='text/markdown',  
    author='Fredrik Saito Odegaardstuen',  
    author_email='frikky@shuffler.io',  
    url='https://github.com/shuffle/shuffle',  
    packages=find_packages(),  
    install_requires=parse_requirements("requirements.txt"),  
    classifiers=[  
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.7',  # Specify Python version requirements
)
