import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
import argparse

def find_emails(text):
    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    return re.findall(email_regex, text)

def get_all_links(url, domain):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'lxml')
    links = set()
    for a_tag in soup.find_all('a', href=True):
        link = urljoin(url, a_tag['href'])
        if urlparse(link).netloc == domain and not link.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx')):
            links.add(link)
    return links

def crawl_emails(start_url):
    domain = urlparse(start_url).netloc
    visited = set()
    emails = set()
    to_visit = {start_url}

    while to_visit:
        url = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)
        print('Visiting: {}'.format(url))

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
            }
            response = requests.get(url, headers=headers)
            response.encoding = response.apparent_encoding
            
            # # Print the content of the page for debugging
            # print(f"Content of {url}:\n{response.text[:500]}\n{'-'*50}")

            page_emails = find_emails(response.text)
            emails.update(page_emails)
            links = get_all_links(url, domain)
            
            # # Print the collected links for debugging
            # print(f"Links found on {url}:")
            for link in links:
                print(link)
            print('-' * 50)
            
            to_visit.update(links - visited)
        except requests.RequestException as e:
            print('Failed to retrieve {}: {}'.format(url, e))

    return emails

def main():
    parser = argparse.ArgumentParser(description='Crawl a website to find email addresses.')
    parser.add_argument('url', help='The start URL to crawl')
    args = parser.parse_args()

    found_emails = crawl_emails(args.url)
    print('Found emails:')
    for email in found_emails:
        print(email)

if __name__ == '__main__':
    main()
