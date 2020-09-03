import sys

import run

if __name__ == '__main__':
    if sys.platform != 'win32':
        msg = 'WARNING! main.py has deprecated, use ./mdmTerminal2/run.sh instead'
        line = lambda: print('+' * (len(msg) + 4))
        line() or print('+ {} +'.format(msg)) or line()
    with run.file_lock(run.LOCKFILE):
        while run.main():
            pass
