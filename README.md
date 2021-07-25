# EDGARConnect
A Python Tool for Batch Downloading SEC EDGAR Filings. Based on the EDGAR download scripts written by Bill McDonald and Tim Loughran, available at https://sraf.nd.edu/textual-analysis/code/.

EDGARConnect improve on this code in several ways. All functionality is wrapped into a single easy-to-use class. The request library's Retry class was used to implement automatic back-off when being rate-limited by the SEC servers. Headers are also used in accordance with SEC request. Users can pass their own User-Agent information (as requested by the SEC here: https://www.sec.gov/os/accessing-edgar-data. Alternatively, User-Agent information can be generated using the fake-useragent package. Finally, EDGARConnect can automatically remove attached files from the SEC filings, significantly cutting down on storage requirements when doing bulk downloads.

Please see the included demo notebook in this Repo for the basics of using EDGARConnect.
