# EDGARConnect
A Python Tool for Batch Downloading SEC EDGAR Filings. Based on the EDGAR download scripts written by Bill McDonald and Tim Loughran, available at https://sraf.nd.edu/textual-analysis/code/.

The code on their site is somewhat out of date, EDGARConnect should be fully Python 3 compatable. In addition, this tool improves on their code in several ways. All functionality is wrapped into a single easy-to-use class. More importantly, the request library's Retry class was used to implement automatic back-off when being rate-limited by the SEC servers.

Please see the included demo notebook in this Repo for the basics of using EDGARConnect.
