#!/usr/bin/env python3

import ssl
import sys
import csv
import socket
import argparse

from datetime import datetime
from urllib.parse import urlparse
from http.client import HTTPConnection, HTTPSConnection

from h2.connection import H2Connection
from h2.config import H2Configuration

import httpx
import requests

def get_source_ips(proxies):
    """
    Retrieve the internal and external IP addresses of the machine.
    
    Accepts:
        proxies (dict): A dictionary of proxies to use for the requests.
    
    Returns:
        tuple: (internal_ip, external_ip)
    """
    try:
        response = requests.get('http://ifconfig.me', timeout=5, proxies=proxies)
        external_ip = response.text.strip()

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        try:
            s.connect(('8.8.8.8', 1))
            internal_ip = s.getsockname()[0]
        except socket.timeout:
            internal_ip = '127.0.0.1'
        except Exception as e:
            internal_ip = '127.0.0.1'
        finally:
            s.close()
        
        return internal_ip, external_ip
    except requests.exceptions.Timeout:
        print("External IP request timed out.")
        return None, None
    except Exception as e:
        print(f"Error: {e}")
        return None, None
    
def check_http2_support(url, proxies):
    """
    Check if the given URL supports HTTP/2.
    
    Parameters:
        url (str): The URL to check.
        proxies (dict): A dictionary of proxies to use for the requests.
        
    Returns:
        tuple: (status, error/version)
        status: 1 if HTTP/2 is supported, 0 otherwise, -1 on error.
        error/version: Error message or HTTP version if not HTTP/2.
    """
    try:
        # Update the proxies dictionary locally within this function
        local_proxies = {}
        if proxies:
            local_proxies = {
                'http://': proxies['http'],
                'https://': proxies['https'],
            }
        
        # Use the proxy if set, otherwise don't
        client_options = {'http2': True, 'verify': False}  # Ignore SSL verification
        if local_proxies:
            client_options['proxies'] = local_proxies
        
        with httpx.Client(**client_options) as client:
            response = client.get(url)
        
        if response.http_version == 'HTTP/2':
            return (1, "")
        else:
            return (0, f"{response.http_version}")
    except Exception as e:
        return (-1, f"check_http2_support - {e}")

def send_rst_stream_h2(host, port, stream_id, uri_path='/', timeout=5, proxy=None):
    """
    Send an RST_STREAM frame to the given host and port.
    
    Parameters:
        host (str): The hostname.
        port (int): The port number.
        stream_id (int): The stream ID to reset.
        uri_path (str): The URI path for the GET request.
        timeout (int): The timeout in seconds for the socket connection.
        proxy (str): The proxy URL, if any.
        
    Returns:
        tuple: (status, message)
        status: 1 if successful, 0 if no response, -1 otherwise.
        message: Additional information or error message.
    """
    try:
        # Create an SSL context to ignore SSL certificate verification
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # Create a connection based on whether a proxy is used
        if proxy and proxy != "":
            proxy_parts = urlparse(proxy)
            if port == 443:
                conn = HTTPSConnection(proxy_parts.hostname, proxy_parts.port, timeout=timeout, context=ssl_context)
                conn.set_tunnel(host, port)
            else:
                conn = HTTPConnection(proxy_parts.hostname, proxy_parts.port, timeout=timeout)
                conn.set_tunnel(host, port)
        else:
            if port == 443:
                conn = HTTPSConnection(host, port, timeout=timeout, context=ssl_context)
            else:
                conn = HTTPConnection(host, port, timeout=timeout)

        conn.connect()

        # Initiate HTTP/2 connection
        config = H2Configuration(client_side=True)
        h2_conn = H2Connection(config=config)
        h2_conn.initiate_connection()
        conn.send(h2_conn.data_to_send())

        # Send GET request headers
        headers = [(':method', 'GET'), (':authority', host), (':scheme', 'https'), (':path', uri_path)]
        h2_conn.send_headers(stream_id, headers)
        conn.send(h2_conn.data_to_send())

        # Listen for frames and send RST_STREAM when appropriate
        while True:
            data = conn.sock.recv(65535)
            if not data:
                break

            events = h2_conn.receive_data(data)
            has_sent = False
            for event in events:
                if hasattr(event, 'stream_id'):
                    if event.stream_id == stream_id:
                        h2_conn.reset_stream(event.stream_id)
                        conn.send(h2_conn.data_to_send())
                        has_sent = True
                        break # if we send the reset once we don't need to send it again because we at least know it worked

            if has_sent: # if we've already sent the reset, we can just break out of the loop
                return (1, "")
            else:
                # if we haven't sent the reset because we never found a stream_id matching the one we're looking for, we can just try to send to stream 1
                
                available_id = h2_conn.get_next_available_stream_id()
                if available_id == 0:
                    # if we can't get a new stream id, we can just send to stream 1
                    h2_conn.reset_stream(1)
                    conn.send(h2_conn.data_to_send())
                    return (0, "Able to send RST_STREAM to stream 1 but could not find any available stream ids")
                else:
                    # if we can get a new stream id, we can just send to that
                    h2_conn.reset_stream(available_id)
                    conn.send(h2_conn.data_to_send())
                    return (1, "")
                    
        conn.close()
        return (0, "No response")
    except Exception as e:
        return (-1, f"send_rst_stream_h2 - {e}")

def extract_hostname_port_uri(url):
    """
    Extract the hostname, port, and URI from a URL.
    
    Parameters:
        url (str): The URL to extract from.
        
    Returns:
        tuple: (hostname, port, uri)
    """
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        port = parsed_url.port
        scheme = parsed_url.scheme
        uri = parsed_url.path  # Extracting the URI
        if uri == "":
            uri = "/"

        if not hostname:
            return -1, -1, ""

        if port:
            return hostname, port, uri

        if scheme == 'http':
            return hostname, 80, uri

        if scheme == 'https':
            return hostname, 443, uri

        return hostname, (80, 443), uri
    except Exception as e:
        return -1, -1, ""

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', required=True)
    parser.add_argument('-o', '--output', default='/dev/stdout')
    parser.add_argument('--proxy', help='HTTP/HTTPS proxy URL', default=None)
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    proxies = {}
    if args.proxy:
        proxies = {
            'http': args.proxy,
            'https': args.proxy,
        }

    internal_ip, external_ip = get_source_ips(proxies)

    with open(args.input) as infile, open(args.output, 'w', newline='') as outfile:
        csv_writer = csv.writer(outfile)
        csv_writer.writerow(['Timestamp', 'Source Internal IP', 'Source External IP', 'URL', 'Vulnerability Status', 'Error/Downgrade Version'])
        
        for line in infile:
            addr = line.strip()
            if addr != "":
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                if args.verbose:
                    print(f"Checking {addr}...", file=sys.stderr)
                
                http2support, err = check_http2_support(addr, proxies)
                
                hostname, port, uri = extract_hostname_port_uri(addr)
                
                if http2support == 1:
                    resp, err2 = send_rst_stream_h2(hostname, port, 1, uri, proxy=args.proxy)
                    if resp == 1:
                        csv_writer.writerow([now, internal_ip, external_ip, addr, 'VULNERABLE', ''])
                    elif resp == -1:
                        csv_writer.writerow([now, internal_ip, external_ip, addr, 'POSSIBLE', f'Failed to send RST_STREAM: {err2}'])
                    elif resp == 0:
                        csv_writer.writerow([now, internal_ip, external_ip, addr, 'LIKELY', 'Got empty response to RST_STREAM request'])
                else:
                    if http2support == 0:
                        csv_writer.writerow([now, internal_ip, external_ip, addr, 'SAFE', f"Downgraded to {err}"])
                    else:
                        csv_writer.writerow([now, internal_ip, external_ip, addr, 'ERROR', err])
