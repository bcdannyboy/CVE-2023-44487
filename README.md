# CVE-2023-44487
Basic vulnerability scanning to see if web servers may be vulnerable to CVE-2023-44487

This tool checks to see if a website is vulnerable to CVE-2023-44487 completely non-invasively.

1. The tool checks if a web server accepts HTTP/2 requests without downgrading them
2. If the web server accepts and does not downgrade HTTP/2 requests the tool attempts to open a connection stream and subsequently reset it
3. If the web server accepts the creation and resetting of a connection stream then the server is definitely vulnerable, if it only accepts HTTP/2 requests but the stream connection fails it may be vulnerable if the server-side capabilities are enabled.

To run,

    $ python3 -m pip install -r requirements.txt

    $ python3 cve202344487.py -i input_urls.txt -o output_results.csv

You can also specify an HTTP proxy to proxy all the requests through with the `--proxy` flag

    $ python3 cve202344487.py -i input_urls.txt -o output_results.csv --proxy http://proxysite.com:1234

The script outputs a CSV file with the following columns

- Timestamp: a timestamp of the request
- Source Internal IP: The internal IP address of the host sending the HTTP requests
- Source External IP: The external IP address of the host sending the HTTP requests
- URL: The URL being scanned
- Vulnerability Status: "VULNERABLE"/"LIKELY"/"POSSIBLE"/"SAFE"/"ERROR"
- Error/Downgrade Version: The error or the version the HTTP server downgrades the request to

*Note: "Vulnerable" in this context means that it is confirmed that an attacker can reset the a stream connection without issue, it does not take into account implementation-specific or volume-based detections*

# Dockerized

Build

    $ docker build -t py-cve-2023-44487 .

Run:

    $ docker run --rm -v /path/to/urls:/shared py-cve-2023-44487 -i /shared/input_urls.txt -o /shared/output_results.csv
