import os
import time
import datetime as dt
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import pandas as pd
import numpy as np

from zipfile import ZipFile
from io import BytesIO

import pytz
from collections import Counter
from EDGARConnectExceptions import SECServerClosedError
from utilities import progress_bar


class EDGARConnect:

    def __init__(self, edgar_path, edgar_url='https://www.sec.gov/Archives', retry_kwargs=None):
        """
        A class for downloading SEC filings from the EDGAR database.

        PARAMS
        ----------------------------
        edgar_path: str or path-like, (required)
            A path where EDGARConnect will write all its output
        edgar_url: str, default: https://www.sec.gov/Archives
            The base URL of the SEC EDGAR database. There probably shouldn't be a need to ever change this, but it's
            here for future-proofing?
        retry_kwargs: dict, default: None, see below
            A dictionary of keyword arguments to pass to requests.packages.urllib3.util.retry.Retry. These are
            important, because the SEC will throw 403 forbidden errors if we send too many requests too quickly. If
            this argument is None, the following settings will be loaded by default:
                total = 8 ## Maximum retries
                backoff_factor = 1 ## The program will retry after
                    {backoff factor} * (2 ** ({number of total retries} - 1))
                    seconds. Not recommended to set this to 0, but you could try something lower than 1. Make it
                    larger than 1 or increase the maximum retries if you're getting blocked.
                status_forcelist = [403, 429, 500, 502, 503, 504] ## response codes to retry on. Importantly, EDGAR uses
                    code 403 when rate-limiting scripts, so that should always be in this list.
                allowed_methods = ["HEAD", "GET", "OPTIONS"]  ## http methods to retry on. We're basically only doing
                GETs, to be honest I don't know why I put the others here (I copied a tutorial a long time ago?)

        RETURNS
        ----------------------------------
        EDGARConnect will create and fill the following directory structure within edgar_path:

        edgar_path
            |
            +---master_indexes
            |   |
            |   +---{year}{quarter}.txt
            |   |
            |   ...
            +---{form_name}
            |   |
            |   +---{Company_CIK}
            |   |   |
            |   |   +---{year}{quarter}
            |   |   |   |
            |   |   |   +---{report_file_name}.txt
            |   |   |

        master_indexes is a collection of pipe-delimited ("|") tables with the following 5 columns:
            CIK, Company_Name, Form_type, Date_filed , Filename.
            Importantly, Filename is a URL pointing to the report on the EDGAR database.

            The master_indexes folder must be constructed using the download_master_indexes() method before EDGARConnect
            can batch-download filings. Downloading master_indexes requires between 1 and 2 GB of disk space.

        Once master_indexes is downloaded, individual forms over user-specified dates can be downloaded using the
        download_requested_filings() method. Note that download settings must first be set using the
        configure_downloader() method.
        """

        if retry_kwargs is None:
            retry_kwargs = dict(total=8, backoff_factor=1,
                                status_forcelist=[403, 429, 500, 502, 503, 504],
                                allowed_methods=["HEAD", "GET", "OPTIONS"])

        self.edgar_url = edgar_url
        retry_strategy = Retry(**retry_kwargs)
        self.adapter = HTTPAdapter(max_retries=retry_strategy)
        self.http = requests.Session()
        self.http.mount("https://", self.adapter)

        self.edgar_path = edgar_path
        self._check_for_required_directories()

        self.forms = dict(
            f_10k=['10-K', '10-K405', '10KSB', '10-KSB', '10KSB40'],
            f_10ka=['10-K/A', '10-K405/A', '10KSB/A', '10-KSB/A', '10KSB40/A'],
            f_10kt=['10-KT', '10KT405', '10-KT/A', '10KT405/A'],
            f_10q=['10-Q', '10QSB', '10-QSB'],
            f_10qa=['10-Q/A', '10QSB/A', '10-QSB/A'],
            f_10qt=['10-QT', '10-QT/A'],
            f_10x=[])

        for key in self.forms.keys():
            self.forms['f_10x'].extend(self.forms[key])

        self.start_date = None
        self.end_date = None
        self.target_forms = None
        self._configured = False

    def download_master_indexes(self, update_range=2, update_all=False):
        """
        Hit up the SEC EDGAR database and grab their master list of filing URLS. Run this after you run
        configure_downloader() so it knows which master indexes to grab.

        Arguments
        ------------------------
        update_range: int, default = 2
            Overwrite the update_range most recent local files with those from the SEC sever.
            Note that it starts with 0, so update_range = 2 will update the current quarter and the last
            quarter.
        update_all: bool, default = False
            If true, the program will overwrite everything stored locally with what is on the SEC sever.
            This is equivalent to setting update_rate to some large number.
        """

        self._check_config()

        start_date = self.start_date
        end_date = self.end_date
        n_quarters = (end_date - start_date).n + 1

        update_quarters = [end_date - i for i in range(update_range)]

        mean_time = 0

        for i in range(n_quarters):
            start = time.time()

            next_date = start_date + i
            force_redownload = update_all or (next_date in update_quarters)

            self._update_master_index(next_date, force_redownload)

            elapsed = time.time() - start
            alpha = 1 / (i + 1)
            mean_time = alpha * elapsed + (1 - alpha) * mean_time
            progress_bar(i, n_quarters, mean_time, f'Downloading {i} / {n_quarters} Master Lists')
        progress_bar(n_quarters, n_quarters, mean_time, f'Downloading {n_quarters} / {n_quarters} Master Lists')

    def configure_downloader(self, target_forms, start_date='01-01-1994', end_date=None):
        """
        Provide parameters for scraping EDGAR. This method must be run before batch downloading via the
        download_requested_filings() method can be executed.

        ***NOTE THAT WITH DEFAULT SETTINGS, EDGARCONNECT WILL DOWNLOAD ALL AVAILABLE DATA 10-X FAMILY FILINGS (INCLUDING
        10-K, 10-Q, AND ALL ASSOCIATED AMENDMENTS)FROM THE SEC EDGAR DATABASE. IN TOTAL, THIS REQUIRES OVER
        100GB OF DATA. ***

        Arguments
        -------------------------------------
        target_forms: str or iterable, default: None
            Name of the forms to be downloaded (10-K, 10-Q, etc), or a list of such form names.
            EDGARConnect has a built-in dictionary of forms that can be passed into this argument.
            To see valid keys and the associated forms, use the show_available_forms() method.

        start_date: str or datetime object, default: '01-01-1994'
            Date to begin scraping from. Earliest available data is 01-01-1994.

        end_date: str or datetime object, default: None
            Date on which to end scraping. If None, it defaults to today's date.
        """

        # Check if the requested forms are keys in the forms list and grab that list if os
        if isinstance(target_forms, str):
            if target_forms.lower() in self.forms.keys():
                target_forms = self.forms[target_forms.lower()]
            elif target_forms.lower() in ['10k', 'all', 'everything']:
                target_forms = self.forms['f_10x']

        self.target_forms = target_forms
        self.start_date = pd.to_datetime(start_date).to_period('Q')

        if end_date is None:
            end_date = dt.datetime.today()
        self.end_date = pd.to_datetime(end_date).to_period('Q')

        self._check_all_required_indexes_are_downloaded()
        self._configured = True

    def download_requested_filings(self, ignore_time_guidelines=False):
        """
        Method for downloading all forums meeting the requirements set in the configure_downloader() method. That method
        must be run before running this one.

        Arguments
        -------------------------
        ignore_time_guidelines: bool, default=False
            By default, SECConnect will periodically check your system clock time to make sure you are accessing EDGAR
            records during the times requested by the SEC (between 9PM and 6AM EST). By passing ignore_time_guidelines,
            you can try to do downloads outside of that time window. Recommended only if downloading a small number of
            filings.

        RETURNS
        --------------------------
        None, see the EDGARConnect.__init__() docstring for an explanation of the directory structure created during
        downloading.
        """

        self._check_config()
        self._time_check(ignore_time_guidelines)

        start_date = self.start_date
        end_date = self.end_date
        n_quarters = (end_date - start_date).n + 1

        print(f'Gathering URLS for the requested forms...')
        required_files = [f'{(start_date + i).year}Q{(start_date + i).quarter}.txt' for i in range(n_quarters)]

        mean_time = 0

        for i, file_path in enumerate(required_files):
            print(f'Beginning scraping from {required_files[i]}')
            self._time_check(ignore_time_guidelines)

            path = os.path.join(self.master_path, file_path)
            df = pd.read_csv(path, delimiter='|')
            df = df.drop_duplicates()

            for form in self.target_forms:
                form_mask = df.Form_type.str.lower() == form.lower()
                target_rows = df.index[form_mask]
                n_iter = len(target_rows)
                if n_iter == 0:
                    print(f'No {form} filings in {start_date + i} found, continuing...')
                else:
                    print(f'Found {n_iter} {form} filings, beginning download...')

                for j, idx in enumerate(target_rows):
                    row = df.loc[idx, :]
                    out_dir, out_path = self._create_output_directories(row)

                    file_already_downloaded = self._check_file_dir_and_paths_exist(out_dir, out_path)

                    if not file_already_downloaded:
                        start_time = time.time()

                        target_url = self.edgar_url + '/' + row['Filename']
                        filing = self.http.get(target_url)

                        with open(out_path, 'w') as file:
                            file.write(filing.content.decode('utf-8', 'ignore'))

                        elapsed = time.time() - start_time
                        alpha = 1 / (j + 1)
                        mean_time = alpha * elapsed + (1 - alpha) * mean_time
                        progress_bar(j, n_iter, mean_time, f'Downloading {start_date + i} {form} {j} / {n_iter}')
                    progress_bar(n_iter, n_iter, mean_time, f'Downloading {start_date + i} {form} {n_iter} / {n_iter}')
                print('')

    def show_available_forms(self):

        print('Available forms:')
        for key, value in self.forms.items():
            print(f'{key} -> {value}')

    def show_download_plan(self):
        self._check_config()
        self._check_all_required_indexes_are_downloaded()

        forms = np.atleast_1d(self.target_forms)
        start_date = self.start_date
        end_date = self.end_date
        n_quarters = (end_date - start_date).n + 1

        form_counter = Counter()
        required_files = [f'{(start_date + i).year}Q{(start_date + i).quarter}.txt' for i in range(n_quarters)]

        for file in required_files:
            file_path = os.path.join(self.master_path, file)
            df = pd.read_csv(file_path, delimiter="|")
            form_counter.update(df.Form_type)

        form_sum = 0

        print(f'EDGARConnect is prepared to download {len(forms)} types of filings between {start_date} and {end_date}')
        for form in forms:
            print(f'\tNumber of {form}s: {form_counter[form]}')
            form_sum += form_counter[form]

        print('=' * 30)
        print(f'\tTotal files: {form_sum}')

        m, s = np.divmod(form_sum, 60)
        h, m = np.divmod(m, 60)
        d, h = np.divmod(h, 24)

        print(f'Estimated download time, assuming 1s per file: {d} Days, {h} hours, {m} minutes, {s} seconds')
        print(f'Estimated drive space, assuming 150KB per filing: {form_sum * 150 * 1e-6:0.2f}GB')

    def _check_config(self):
        if not self._configured:
            raise ValueError("First define scrape parameters using the build_payload() method")

    def _check_for_required_directories(self):
        self.master_path = os.path.join(self.edgar_path, 'master_indexes')

        self._master_paths_configured = os.path.isdir(self.master_path)
        if not self._master_paths_configured:
            os.mkdir(self.master_path)

    def _check_all_required_indexes_are_downloaded(self):
        start_date = self.start_date
        end_date = self.end_date
        n_quarters = (end_date - start_date).n + 1

        index_files = os.listdir(self.master_path)
        required_files = [f'{(start_date + i).year}Q{(start_date + i).quarter}.txt' for i in range(n_quarters)]

        file_checks = [file in index_files for file in required_files]

        if not all(file_checks):
            error = 'Not all requested dates have an downloaded index file, including:\n'
            for i, check in enumerate(file_checks):
                if not check:
                    error += f'\t {required_files[i]}\n'
            error += 'Have you run the method download_master_indexes() to sync local records with the SEC database?'
            raise ValueError(error)

    def __repr__(self):
        out = 'SEC Edgar Scraper for Python, v0.0\n'
        if not self._configured:
            out += 'Files to be scraped have NOT been defined.\n'
            out += 'Choose scraping targets using the configure_downloader() method'

        else:
            out += 'EDGARConnect is configured for scraping.\n'
            out += f'\t Target Forms: {self.target_forms}\n'
            out += f'\t Date Range: {self.start_date} to {self.end_date}\n'

        return out

    def _update_master_index(self, date, force_redownload):
        target_year = date.year
        target_quarter = date.quarter
        target_url = f'{self.edgar_url}/edgar/full-index/{target_year}/QTR{target_quarter}/master.zip'

        out_path = os.path.join(self.master_path, f'{target_year}Q{target_quarter}.txt')
        file_downloaded = True

        if not os.path.isfile(out_path):
            file_downloaded = False
            with open(out_path, 'w') as file:
                file.write('CIK|Company_Name|Form_type|Date_filed|Filename\n')

        if not file_downloaded or force_redownload:
            master_zip = self.http.get(target_url)
            master_list = ZipFile(BytesIO(master_zip.content))
            master_list = master_list.open('master.idx') \
                .read() \
                .decode('utf-8', 'ignore') \
                .splitlines()[11:]

            with open(out_path, 'a') as file:
                for line in master_list:
                    file.write(line)
                    file.write('\n')

    def _create_output_directories(self, row):
        cik = row['CIK']
        zeros = '0' * (10 - len(str(cik)))
        cik_str = zeros + str(cik)

        dirsafe_form = row['Form_type'].replace('/', '')

        date = pd.to_datetime(row['Date_filed']).to_period('Q')
        date_str = str(date)

        filename = row['Filename'].split('/')[-1]

        out_dir = os.path.join(self.edgar_path, dirsafe_form, cik_str, date_str)
        out_path = os.path.join(out_dir, filename)

        return out_dir, out_path

    @staticmethod
    def _check_file_dir_and_paths_exist(out_dir, out_path):
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)

        return os.path.isfile(out_path)

    @staticmethod
    def _check_time_is_SEC_recommended():
        sec_server_open = 21
        sec_server_close = 6
        local_time = dt.datetime.now().astimezone()
        est_timezone = pytz.timezone('US/Eastern')
        est_dt = local_time.astimezone(est_timezone)

        if est_dt.hour >= sec_server_open or est_dt.hour < sec_server_close:
            return False
        else:
            return True

    def _time_check(self, ignore_time_guidelines=False):
        SEC_servers_open = self._check_time_is_SEC_recommended()

        if not SEC_servers_open:
            print('''SEC guidelines request batch downloads be done between 9PM and 6AM EST. If you plan to download
                     a lot of stuff, it is strongly recommended that you wait until then to begin. If your query size 
                     is relatively small, or if it's big but you feel like ignoring this guidance from the good people 
                     at the SEC, re-run this function with the argument:
                     
                     ignore_time_guidelines = True''')

            if not ignore_time_guidelines:
                raise SECServerClosedError()
