"""
this script performs authentication operations
needed to connect to STAC server
"""
import os
from netrc import netrc
from platform import system
from decouple import config
from .helpers import get_project_root


def get_netrc_path():
    """
    gets the netrc file path
    Returns:
        string -- full path of netrc file
    """
    root_dir = get_project_root()
    # Determine the OS (Windows machines usually use an '_netrc' file)
    netrc_fname = "_netrc" if system() == "Windows" else ".netrc"
    # Determine if netrc file exists, and if so, if it includes NASA
    # Earthdata Login Credentials
    full_fpath = os.path.join(root_dir, netrc_fname)
    return full_fpath


def setup_netrc():
    """
    sets up netrc file if not done yet
    """
    netrc_path = get_netrc_path()
    if not os.path.exists(netrc_path):
        with open(netrc_path, 'a', encoding="utf-8") as the_file:
            machine = config('NASA_MACHINE', cast=str)
            login = config('NASA_LOGIN', cast=str)
            passwd = config('NASA_PASS', cast=str)
            the_file.write(f'machine {machine}\n')
            the_file.write(f'login {login}\n')
            the_file.write(f'password {passwd}\n')


def authenticate():
    """
    authentication method
    """
    netrc_path = get_netrc_path()
    try:
        netrc(netrc_path).authenticators(config('NASA_MACHINE', cast=str))[0]
    except TypeError:
        print('ERROR in authentication!')
    # except:
    #     logger("error in authentication!")
