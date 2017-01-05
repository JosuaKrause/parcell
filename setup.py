# -*- coding: utf-8 -*-
"""
Created on 2016-12-23

@author: joschi <josua.krause@gmail.com>

Parcell helps you to keep your work on your machine even when it needs to be
executed remotely. This is done by sending your project's code to one of your
beefy worker servers, running the code, and sending the results back. Multiple
tasks can be run in parallel and on different servers to balance the load. You
can keep improving your code on your machine without lag and get notified when
submitted tasks have been completed. No setup on the server side is required.
"""

import os
import sys

from codecs import open
from setuptools import setup

os.chdir(os.path.abspath(os.path.dirname(__file__)))

def list_files(d, root):
    files = []
    for e in os.listdir(os.path.join(root, d)):
        if os.path.isdir(os.path.join(root, d, e)):
            files.extend(list_files('%s/%s' % (d, e), root))
        elif not e.endswith('.pyc'):
            files.append('%s/%s' % (d, e))
    return files

# NOTE! steps to distribute:
#$ git submodule update --init --recursive
#$ python setup.py sdist bdist_wheel
#$ twine upload dist/... <- here be the new version!

with open('README.rst', encoding='utf-8') as f:
    long_description = f.read()
req = [ 'quick_server', 'quick_cache', 'pexpect', 'tej' ]
if sys.version_info < (2, 7):
    req.append('argparse')
setup(
    name='parcell',
    version='0.2.1',
    packages=['parcell'],
    package_data={
        'parcell': list_files('www', 'parcell') + list_files('default_envs', 'parcell'),
    },
    entry_points={
          'console_scripts': [ 'parcell = parcell.main:main' ],
    },
    install_requires=req,
    description='UI for local development of server executed projects.',
    author='Josua Krause',
    author_email='josua.krause@gmail.com',
    maintainer='Josua Krause',
    maintainer_email='josua.krause@gmail.com',
    url='https://github.com/JosuaKrause/parcell/',
    long_description=long_description,
    license='MIT',
    keywords=[
        'parcell',
        'remote',
        'execution',
        'project',
        'management',
        'web',
        'UI',
    ],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Information Technology',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2',
    ]
)
