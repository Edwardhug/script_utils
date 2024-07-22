import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
import argparse

def find_emails(text):
    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    return re.findall(email_regex, text)

def get_all_links(url, domain):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'lxml')
    links = set()
    for a_tag in soup.find_all('a', href=True):
        link = urljoin(url, a_tag['href'])
        if urlparse(link).netloc == domain:
            if not link.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx')):
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
            response = requests.get(url)
            response.encoding = response.apparent_encoding  # Handle character encoding issues
            page_emails = find_emails(response.text)
            emails.update(page_emails)
            links = get_all_links(url, domain)
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
