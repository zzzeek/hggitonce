from setuptools import setup


setup(name='hggitonce',
      version=1.0,
      description="migrate hg to git one way",
      classifiers=[
      'Development Status :: 4 - Beta',
      'Environment :: Console',
      'Programming Language :: Python',
      'Programming Language :: Python :: Implementation :: CPython',
      'Programming Language :: Python :: Implementation :: PyPy',
      ],
      author='Mike Bayer',
      author_email='mike@zzzcomputing.com',
      url='http://bitbucket.org/zzzeek/hggitonce',
      license='MIT',
      packages=["hggitonce"],
      zip_safe=False,
      install_requires=['dulwich>=0.8.6'],
      entry_points={
        'console_scripts': ['hggitonce = hggitonce.cmd:main'],
      }
)
