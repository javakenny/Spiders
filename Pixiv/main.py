import requests
import urllib
import logging
import json
import re
from bs4 import BeautifulSoup as bs
import os
import sys
from multiprocessing.dummy import Pool as ThreadPool
import time

path = 'img'

class PixivItem():
    def __init__(self, illust_id, headers):
        self.illust_id = illust_id
        self.pageURL = f'https://www.pixiv.net/member_illust.php?mode=medium&illust_id={self.illust_id}'
        self.headers = headers
        self.session = requests.Session()
        self.session.headers = self.headers

    def downloadImageTo(self, url, imageName):
        if os.path.exists(imageName):
            logging.debug('img existed. skipping...')
            return
        try:
            h = {
                'Referer':self.headers['Referer'],
                'User-Agent':self.headers['User-Agent']
            }
            response = requests.get(url, headers = h)
            if response.status_code != 200:
                logging.error(f'{response.status_code} Error, retrying...')
                raise ConnectionError
        except ConnectionError as ex:
            response = self.session.get(url, headers=self.headers)
            if response.status_code == 403:
                logging.error('403 Error.')
                print(self.session.headers)
                quit()
        with open(imageName, 'wb') as f:
            f.write(response.content)

    def downloadImage(self, url):
        imageName = path + os.sep + self.title + ' - ' + self.artist + '.' + url.split('.')[-1]
        imageName = imageName.replace('*', '※').replace('?','？')
        self.downloadImageTo(url, imageName)

    def getTitleAndArtist(self, soup):
        # soup = bs(pageContent, 'html.parser')
        pageTitle = soup.head.find_all('meta', {'property':"og:title"})[0]['content']
        logging.debug(f'get page title: "{pageTitle}"')
        res = re.findall(r'^「(.+)」/「([^」]+)」\[pixiv\]$', pageTitle)[0]
        self.title = res[0]
        self.artist = res[1].replace('.', '·')
        self.title = re.sub(r'[\|\/]', '', self.title)
        self.artist = re.sub(r'[\|\/]', '', self.artist)

        logging.debug(f'title: "{self.title}", artist: "{self.artist}"')

    def getSoup(self, url):
        pageContent = self.getContent(url)
        soup = bs(pageContent, 'html.parser')
        return soup

    def getContent(self, url):
        pageResponse = self.session.get(url)
        pageContent = pageResponse.content.decode()
        return pageContent

class PixivSinglePic(PixivItem):
    def __init__(self, illust_id, headers):
        PixivItem.__init__(self, illust_id, headers)
        self.session.headers['Referer'] = self.pageURL

    def getPic(self):
        logging.info(f'getting pic {self.illust_id}...')
        soup = self.getSoup(self.pageURL)
        logging.debug(f'page for {self.illust_id} get.')

        # get title and artist
        self.getTitleAndArtist(soup)

        # get pic url
        imgSoups = soup.find_all('img', {'class':"original-image"})
        if len(imgSoups) == 0:
            logging.error('no img url found.')
            return
        self.oriImageURL = imgSoups[0]['data-src']
        logging.debug(f'get oriImageURL: {self.oriImageURL}')

        # download
        self.downloadImage(self.oriImageURL)
        logging.info(f'picture {self.title} - {self.artist} ({self.illust_id}) done.')

class PixivAlbum(PixivItem):
    def __init__(self, illust_id, headers):
        PixivItem.__init__(self, illust_id, headers)
        self.albumURL = f'https://www.pixiv.net/member_illust.php?mode=manga&illust_id={illust_id}'
        self.session.headers['Referer'] = self.albumURL
    
    def getAlbum(self):
        logging.info(f'getting album {self.illust_id}...')
        
        # get title
        soup = self.getSoup(self.pageURL)
        logging.debug(f'page for {self.illust_id} (main page) get.')
        self.getTitleAndArtist(soup)
        
        # get pic urls
        picURLs = set()
        soup = self.getSoup(self.albumURL)
        imageContainers = soup.find_all('div', {'class':'item-container'})
        for item in imageContainers:
            picURLs.add(item.img['data-src'])
        
        # mkdir
        thisPath = path + os.sep + self.title + ' - ' + self.artist
        if not os.path.exists(thisPath):
            os.mkdir(thisPath)

        self.count = 1
        def func(url):
            self.downloadImage(url)
            logging.debug(f'({self.title} - {self.artist}) pic {self.count} done.')
            self.count += 1
        pool = ThreadPool(5)
        pool.map(func, picURLs)
        pool.close()
        pool.join()

        logging.info(f'album {self.title} - {self.artist} ({self.illust_id}) done.')

    def downloadImage(self, url):
        thisPath = path + os.sep + self.title + ' - ' + self.artist

        num = re.findall(r'p(\d+)', url)[0]
        imageName = thisPath + os.sep + num + '.' + url.split('.')[-1]
        imageName = imageName.replace('*', '※').replace('?','？')
        self.downloadImageTo(url, imageName)

class PixivResult():
    def __init__(self):
        # get config
        self.config = self.getConfig()
        self.headers = self.config['headers']
        logging.debug(f'__init__ get config done.')

    def getPage(self, keyword, page=1):
        logging.info(f'beginning to get page {page}')

        keywordEncoded = urllib.parse.quote(keyword)
        searchPageURL = f'https://www.pixiv.net/search.php?word={keywordEncoded}&order=date_d&p={page}'
        logging.debug(f'search word = "{keyword}"')

        # get result page
        searchPageResponse = requests.get(searchPageURL, headers=self.headers)
        searchPage = searchPageResponse.content.decode()
        logging.debug(f'get searchPage content.')

        # get result list
        soup = bs(searchPage, 'html.parser')
        imageList = soup.find_all('li', {'class':'image-item'})

        # add to set
        picSet = set()
        albumSet = set()
        for item in imageList:
            illust_id = re.findall(r'illust_id=(\d+)', str(item))[0]
            if len(item.a['class']) == 3:
                # single
                picSet.add(illust_id)
            elif 'multiple' in item.a['class']:
                # album
                albumSet.add(illust_id)
            else:
                # unknown
                pass
        logging.debug(f'picSet: {picSet}')
        logging.debug(f'albumSet: {albumSet}')

        # get
        self.getPics(picSet)
        self.getAlbums(albumSet)

    def getPics(self, picSet):
        # for illust_id in picSet:
        #     self.getPic(illust_id)
        def func(x):
            self.getPic(x)
            time.sleep(1)
        pool = ThreadPool(5)
        pool.map(func, picSet)
        pool.close()
        pool.join()
    
    def getAlbums(self, albumSet):
        # for illust_id in albumSet:
        #    self.getAlbum(illust_id)
        def func(x):
            self.getAlbum(x)
            time.sleep(1)
        pool = ThreadPool(3)
        pool.map(func, albumSet)
        pool.close()
        pool.join()

    def getConfig(self):
        with open('config.json') as f:
            res = json.load(f)
        return res

    def getPic(self, illust_id):
        PixivSinglePic(illust_id, self.headers).getPic()

    def getAlbum(self, illust_id):
        PixivAlbum(illust_id, self.headers).getAlbum()

def getPixiv(keyword, page=1):
    logging.debug(f'starting to get pixiv (keyword = "{keyword}", page={page})')
    if not os.path.exists(path):
        os.mkdir(path)
    for i in range(page):
        PixivResult().getPage(keyword, i+1)

def main():
    logging.basicConfig(level=logging.INFO,
        format='(%(asctime)s) - [%(levelname)s] %(message)s',
        datefmt='%y-%m-%d %H:%M:%S')
    keyword = ''
    page = 5
    for item in sys.argv[1:]:
        if item.upper() in ('-D', '-DEBUG'):
            logging.basicConfig(level=logging.DEBUG,
                format='(%(asctime)s) - [%(levelname)s] %(message)s',
                datefmt='%y-%m-%d %H:%M:%S')
        elif 'page=' in item.lower():
            num = int(re.findall('page=(\d*)', item)[0])
        else:
            keyword += item + ' '
    keyword = keyword[:-1]

    if len(keyword) == 0:
        keyword = '1000users入り エロマンガ'
    getPixiv(keyword, page)
    
    # PixivResult().getPage('1000users入り エロマンガ', 4)
    # PixivResult().getPage('1000users入り エロマンガ', 5)

if __name__ == '__main__':
    main()
