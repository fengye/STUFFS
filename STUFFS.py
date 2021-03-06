#!/usr/bin/python -OO

#License, reuse, etc.
#--------------------
#
#This software was originally written by Aaron Laursen <aaronlaursen@gmail.com>.
#
#This software is licensed under the ISC (Internet Systems Consortium) 
#license. The specific terms below for allow pretty much any reasonable use. 
#If you, for some reason, need it in a different licence, send me an email, 
#and we'll see what I can do. 
#
#However, the author would appreciate but does not require (except as 
#permitted by the ISC license):
#
#- Notification (by email preferably <aaronlaursen@gmail.com>) of use in
#products, whether open-source or commercial. 
#
#- Contribution of patches or pull requests in the case of
#  improvements/modifications
#
#- Credit in documentation, source, etc. especially in the case of 
#  large-scale projects making heavy use of this software.
#
#### ISC license
#
#Copyright (c) 2013, Aaron Laursen <aaronlaursen@gmail.com>
#
#Permission to use, copy, modify, and/or distribute this software for any 
#purpose with or without fee is hereby granted, provided that the above 
#copyright notice and this permission notice appear in all copies.
#
#THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES 
#WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF 
#MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR 
#ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES 
#WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN 
#ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF 
#OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.


from sqlalchemy import Table, Column, Integer, ForeignKey, BLOB, \
        Boolean, String, create_engine, MetaData
from sqlalchemy.orm import relationship, backref, sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from time import time
from sqlalchemy.dialects.mysql import VARCHAR, TEXT
from stat import S_IFDIR, S_IFLNK, S_IFREG
from hashlib import md5
from fuse import Operations, LoggingMixIn, FUSE, FuseOSError
from sys import argv
from errno import ENOENT
from nltk.corpus import wordnet


#database stuff

from sqlalchemy.engine import Engine
from sqlalchemy import event

#'''
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute('PRAGMA synchronous=OFF')
    cursor.execute('PRAGMA count_changes=OFF;')
    #cursor.execute('PRAGMA mmap_size=268435456;')
    cursor.close()
#'''

DBPATH="fs.db" if len(argv) <=2 else argv[2]
db = create_engine('sqlite:///'+DBPATH,connect_args={'check_same_thread':False})
#db = create_engine('sqlite:////tmp/stuffs.db')
#db = create_engine('mysql+oursql://stuffs:stuffs@localhost/stuffs_db')
db.echo = False
Base = declarative_base(metadata=MetaData(db))
Session = scoped_session(sessionmaker(bind=db))
#session=Session()

Table('use'
    , Base.metadata
    , Column('file_id', Integer, ForeignKey('files.id'), index=True)
    #, Column('tag_id', Integer, ForeignKey('tags.id'), index=True)
    , Column('tag_name', String, ForeignKey('tags.name'), index=True)
    #, mysql_engine = "InnoDB"
    #, mysql_charset= "utf8"
)

class Datum(Base):
    __tablename__='data'
    #__table_args__={
    #        'mysql_engine':'InnoDB'
    #        ,'mysql_charset':'utf8'
    #        }
    def __init__(self):
        self.datum=bytes()
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey('files.id'), index=True)
    datum = Column(BLOB(length=4*1024))

class File(Base):
    __tablename__ = 'files'
    #__table_args__={
    #        'mysql_engine':'InnoDB'
    #        ,'mysql_charset':'utf8'
    #        }
    def __init__(self):
        pass
    id = Column(Integer, primary_key=True)
    #attrs = Column(String)
    attrs = Column(String(length=512))
    name = Column(String(length=256), index=True)
    data = relationship("Datum"
                    , collection_class=list
                    )
    tags = relationship("Tag"
                    , secondary="use"
                    , backref=backref("files", collection_class=set)
                    , collection_class=set
                    )

class Tag(Base):
    __tablename__ = 'tags'
    def __init__(self, txt):
        self.name=txt
    #id = Column(Integer, primary_key=True)
    name = Column(String(length=256), primary_key=True)#nullable=False, unique=True, index=True)
    attrs = Column(String(length=512))

Base.metadata.create_all()

def mkfile(name, session, mode=0o770, tags=None):
    f = File()
    session.add(f)
    if tags !=None:
        f.tags |= set(tags)
    now=time()
    a = {'st_mode':(S_IFREG | mode)
                , 'st_nlink':1
                , 'st_size':0
                , 'st_ctime':now
                , 'st_mtime':now
                , 'st_atime':now
                , 'uid':0
                , 'gid':0
                }
    f.attrs = convertAttr(a)
    f.name=name
    addBlock(f,session)
    #f.data=bytes()
    #print("****new file tags:", tags)
    return f

def mktag(txt, session, mode=0o777):
    t=Tag(txt)
    session.add(t)
    now=time()
    a = {'st_mode':(S_IFDIR | mode)
                , 'st_nlink':1
                , 'st_size':0
                , 'st_ctime':now
                , 'st_mtime':now
                , 'st_atime':now
                , 'uid':0
                , 'gid':0
                }
    t.attrs = convertAttr(a)
    return t

'''
def getAttrTag(obj, attr, session):
    q=session.query(Tag).filter(Tag.in_(obj.tags), Tag.name.like("attr::"+attr+"::%") )
    return q.first()

def setAttrTag(obj, attr, value, session):
    obj.tags.discard(getAttrTag(obj,attr,session))
    t=getTagsByTxts("attr::"+attr+"::"+value)
#'''

def getSimTerms(term):
    t = wordnet.synsets(term)
    terms=set()
    for syn in t:
        for name in syn.lemma_names():
            terms.add(name)
        for hypo in syn.hyponyms():
            for name in hypo.lemma_names():
                terms.add(name)
        for hyper in syn.hypernyms():
            for name in hyper.lemma_names():
                terms.add(name)
    return terms

def getSimTagsFromTerm(term,session):
    terms=getSimTerms(term)
    tags=getTagsByTxts(set(terms),session)
    return tags

def getSimTags(tag,session):
    terms = getSimTerms(tag.name)
    tags=getTagsByTxts(terms,session)
    return tags

def convertAttr(attrs):
    attrdata=( ('st_mode',int)
            , ('st_nlink',int)
            , ('st_size',int)
            , ('st_ctime',float)
            , ('st_mtime',float)
            , ('st_atime',float)
            , ('uid', int)
            , ('gid', int)
            )
    if type(attrs) == type(dict()):
        s=''
        for i in range(len(attrdata)):
            s+=str(attrs[attrdata[i][0]])
            s+=','
        return s[:-1]
    if type(attrs) == type(''):
        attrs=attrs.split(',')
        d={attrdata[i][0]:attrdata[i][1](attrs[i]) for i in range(len(attrdata))}
        return d
    return None

def getIdFromString(s):
    t={'%':Tag,'@':File}
    if len(s) <3: return 0, File
    if s[-1] not in ('%','@'):
        return 0, File
    if len(s.split(s[-1]))<3:
        return 0, File
    i=s.split(s[-1])[-2]
    if not i.isdigit():
        return 0, File
    return int(i), t[s[-1]]

def genDisplayName(obj):
    if obj.__tablename__=='files':
        name=obj.name
        s='@'
        name += s + str(obj.id) +s
    elif obj.__tablename__=='tags':
        name=obj.name
        s='%'
    return name

def getByID(id_, session, typ=File):
    return session.query(typ).get(int(id_))

def getFilesByTags(tags,session):
    q=session.query(File)
    for t in tags:
        q=q.filter(File.tags.contains(t))
    return q.all()

def getFilesByLogicalTags(tags,session):
    if len(tags[0])+len(tags[1])+len(tags[2]) ==0: return None
    q=session.query(File)
    for t in tags[0]:
        q=q.filter(File.tags.contains(t))
    for t in tags[1]:
        q=q.filter(~File.tags.contains(t))
    #for op in tags[2]:
    #    q=q.filter(File.tags.isdisjoint(op[0]))
    #    q=q.filter(~File.tags.isdisjoint(op[1]))
    if len(tags[2])==0: return q.all()
    #t=set(q.all())
    t=set()
    for op in tags[2]:
        for i in op[0]:
            s=set(q.filter(File.tags.contains(i)).all())
            t|=s
        for i in op[1]:
            s=set(q.filter(~File.tags.contains(i)).all())
            t|=s
    return t

def getTagsByTxts(txts,session):
    q=session.query(Tag).filter(Tag.name.in_(txts))
    return q.all()

def getFilesByTagTxts(txts,session):
    tags=getTagsByTxts(txts,session)
    return getFilesByTags(tags,session)

def getTagsByFiles(files):
    tags=set()
    for f in files:
        tags |= f.tags
    return tags

def getTagsFromPath_logical(path,session):
    elems=set(path.split('/'))
    elems.discard('')
    parts=[set(),set(),[]] #[need,not,opt]
    if len(elems)==0: return parts
    for elem in elems:
        #or case
        if elem[0]=="%" and elem[-1]=="%":
            opts = elem[1:-1].split("%")
            p=set()
            n=set()
            for opt in opts:
                if opt[0]=="!" and len(opt)>1: n.add(opt[1:])
                else: p.add(opt)
            p=getTagsByTxts(p,session)
            n=getTagsByTxts(n,session)
            parts[2].append([p,n])
        elif elem[0]==elem[-1]=="?":
            print("asdf")
            e=elem[1:-1]
            neg=False
            if e[0]=="!":
                e=e[1:]
                neg=True
            #t=getTagsByTxts(set([elem[1:-1]]),session)
            #if len(t)==0: continue
            #simt=getSimTags(t[0],session)
            if len(e)<1: continue
            simt=getSimTagsFromTerm(e,session)
            if not neg: parts[2].append([simt,set()])
            else: parts[2].append([set(),simt])
            print(simt)
        elif elem[0]=="!" and len(elem)>1: parts[1].add(elem[1:])
        else: parts[0].add(elem)
    parts[0]=set(getTagsByTxts(parts[0],session))
    parts[1]=set(getTagsByTxts(parts[1],session))
    return parts

def getTagsFromPath(path,session):
    #print("----------------------")
    #print("%"+path+"%")
    tagnames=set(path.split('/'))
    tagnames.discard('')
    #print(tagnames)
    #print("----------------------")
    if type(tagnames)==type(None): return set()
    if len(tagnames)==0: return set()
    idtags=set()
    for t in tagnames:
        id_,typ = getIdFromString(t)
        tag=getByID(id_, session, Tag)
        if tag: idtags.add(tag)
    nametags=set(getTagsByTxts(tagnames,session))
    return idtags | nametags

def getEndTagFromPath(path,session):
    #if path=='/': return None
    path=path.strip('/')
    path=path.split("/")
    tagname=path[-1]
    if tagname=='': return None
    id_, typ = getIdFromString(tagname)
    tag=getByID(id_, session, Tag)
    if tag: return tag
    return getTagsByTxts(tagname,session)[0]

def getFileByNameAndTags(name,tags,session):
    #print(tags)
    if len(tags)==0:return None
    q=session.query(File).filter(File.name==name)
    for t in tags:
        q=q.filter(File.tags.contains(t))
    return q.first()

def getFileByNameAndLogicalTags(name,tags,session):
    if len(tags[0])+len(tags[1])+len(tags[2]) ==0: return None
    q=session.query(File).filter(File.name==name)
    for t in tags[0]:
        q=q.filter(File.tags.contains(t))
    for t in tags[1]:
        q=q.filter(~File.tags.contains(t))
    #for op in tags[2]:
    #    q=q.filter(File.tags.isdisjoint(op[0]))
    #    q=q.filter(~File.tags.isdisjoint(op[1]))
    #return q.first()
    if len(tags[2])==0: return q.first()
    for op in tags[2]:
        for i in op[0]:
            s=q.filter(File.tags.contains(i)).first()
            if s: return s
        for i in op[1]:
            s=q.filter(~File.tags.contains(i)).first()
            if s: return s
    return None

def getFileFromPath(path,session):
    path=path.strip('/')
    pieces=path.split('/')
    fstring=pieces[-1]
    fid,typ=getIdFromString(fstring)
    f=getByID(fid, session, File)
    if f: return f
    if len(pieces) < 2: return None
    path = ""
    for p in pieces[:-1]: path +=p+"/"
    return getFileByNameAndLogicalTags(fstring,getTagsFromPath_logical(path,session),session)

def getSubByTags(tags,session):
    if len(tags)==0:return genAllTags(session)
    subfiles=set(getFilesByTags(tags,session))
    subtags=getTagsByFiles(subfiles)
    subtags=subtags-tags
    #print("{}{}{}{}{}{}{}")
    #print(subfiles,subtags)
    #print("{}{}{}{}{}{}{}")
    return subfiles | subtags

def getSubByTags_logical(tags,session):
    if len(tags[0])+len(tags[1])+len(tags[2])==0:return genAllTags(session)
    subfiles=set(getFilesByLogicalTags(tags,session))
    subtags=getTagsByFiles(subfiles)
    subtags=subtags-tags[0]-tags[1]
    return subfiles | subtags

def genSub(path,session):
    tags=getTagsFromPath(path,session)
    #print("\n tags from subpath", path,tags,"\n")
    sub=getSubByTags(tags,session)
    #print("############")
    #print(sub)
    #print("############")
    return sub

def genSubLogical(path,session):
    tags=getTagsFromPath_logical(path,session)
    sub=getSubByTags_logical(tags,session)
    return sub

def genSubDisplay(path,session):
    sub=genSub(path,session)
    return [genDisplayName(x) for x in sub]

def genSubDisplayLogical(path,session):
    sub=genSubLogical(path,session)
    return [genDisplayName(x) for x in sub]

def getAttrByObj(obj):
    return convertAttr(obj.attrs)

def getObjByPath(path,session):
    if path[-1]=='/':
        return getEndTagFromPath(path,session)
    objname=path.split('/')[-1]
    #print("============")
    #print(objname)
    #print(getIdFromString(objname))
    #print("============")
    obj=None
    id_, typ = getIdFromString(objname)
    obj = getByID(id_, session,typ)
    if obj: return obj
    pathpieces=path.rsplit('/',1)
    opts=genSubLogical(pathpieces[0]+'/',session)
    if pathpieces[1][0]==pathpieces[1][-1]=="%":
        ors=set(pathpieces[1].split("%"))
        ors.discard('')
        ors=set(getTagsByTxts(ors, session))
        if len(ors)>=1 and not ors.isdisjoint(opts): return list(ors.intersection(opts))[0]
    for o in opts:
        if o.name==pathpieces[1]: return o
        if "!"==pathpieces[1][0] and o.name==pathpieces[1][1:]: return o
    if typ == File and len(path.split('/'))>2 and 'ALLFILES' not in path.split('/'):
        obj = getFileByNameAndLogicalTags(objname.rsplit('@',2)[0],getTagsFromPath_logical(path,session),session)
        return obj
    return getFileFromPath(path,session)

def genEverything(session):
    stuff=set()
    q=session.query(File)
    stuff |= set(q.all())
    q=session.query(Tag)
    stuff |= set(q.all())
    #print("------stuff:",stuff)
    return stuff

def genAllTags(session):
    stuff=set(session.query(Tag).all())
    return stuff

def genAllFiles(session):
    stuff=set(session.query(File).all())
    return stuff

def genDisplayEverything(session):
    stuff=genEverything(session)
    return [genDisplayName(obj) for obj in stuff]

def genDisplayAllTags(session):
    stuff=genAllTags(session)
    return [genDisplayName(obj) for obj in stuff]

def genDisplayAllFiles(session):
    stuff=genAllFiles(session)
    return [genDisplayName(obj) for obj in stuff]

def getAttrByPath(path,session):
    obj=getObjByPath(path,session)
    if not obj: return None
    return getAttrByObj(obj)

def rmObj(obj,session):
    session.delete(obj)

def rmByPath(path,session):
    obj=getObjByPath(path,session)
    if not obj: return None
    rmObj(obj,session)

def addBlock(f,session):
    block=Datum()
    session.add(block)
    f.data.append(block)
    #block.parent_id=f.id
    #session.flush()
    return f

def delBlock(f,session):
    session.delete(f.data.pop())
    #session.flush()
    return f

#fuse stuff
class STUFFS(LoggingMixIn, Operations):
    def __init__(self):
        self.fd=0
        #self.session=Session()
        self.blocksize=4*1024

    def getattr(self, path, fh=None):
        #print("getattr:", path, fh)
        session=Session()
        attr=None
        if path.strip()=='/' or path.split('/')[-1]=='ALLFILES' \
            or (path.split('/')[-2]=='ALLFILES' and path.split('/')[-1]=='') \
            or (path.split("/")[-1][0]==path.split("/")[-1][-1]=="?"):
            attr= {'st_mode':(S_IFDIR | 0o777)
                , 'st_nlink':2
                , 'st_size':0
                , 'st_ctime':time()
                , 'st_mtime':time()
                , 'st_atime':time()
                , 'uid':0
                , 'gid':0
                }
        pieces=path.rsplit("/",1)
        if len(pieces)>0 and len(pieces[-1])>0 and pieces[-1][0]=='!':
            pieces[-1]=pieces[-1][1:]
            path='/'.join(pieces)
        if not attr:
            attr=getAttrByPath(path,session)
        #print("+++++++++")
        #print(attr)
        #print("+++++++++")
        if not attr:
            raise FuseOSError(ENOENT)
        return attr

    def mkdir(self,path,mode):
        session=Session()
        path=path.strip('/')
        path=path.split('/')
        txt=path[-1]
        mktag(txt, session, mode)
        session.commit()
        Session.remove()

    def readdir(self,path,fh=None):
        #print("readdir")
        session=Session()
        #if path=='/': return ['.','..']+genDisplayEverything(session)
        if path=='/': return ['.','..']+genDisplayAllTags(session)+['ALLFILES']
        if 'ALLFILES' == path.split('/')[-1] or \
            ('ALLFILES'==path.split('/')[-2] and ''==path.split('/')[-1]):
            return ['.','..']+genDisplayAllFiles(session)
        return ['.','..']+genSubDisplayLogical(path,session)

    def chmod(self, path, mode):
        session=Session()
        obj=getObjByPath(path,session)
        if not obj: return
        attrs=convertAttr(obj.attrs)
        attrs['st_mode'] |=mode
        obj.attrs=convertAttr(attrs)
        session.commit()
        Session.remove()
        return 0

    def chown(self, path,uid,gid):
        session=Session()
        obj=getObjByPath(path,session)
        if not obj: return
        attrs=convertAttr(obj.attrs)
        attrs['uid']=uid
        attrs['gid']=gid
        obj.attrs=convertAttr(attrs)
        session.add(obj)
        session.commit()
        Session.remove()

    def create(self,path,mode):
        #print("creat reached:",path,mode)
        session=Session()
        tpath, name = path.rsplit("/",1)
        tags=getTagsFromPath_logical(path,session)[0]
        mkfile(name,session,tags=tags)
        session.commit()
        Session.remove()
        self.fd +=1
        return self.fd

    def open(self,path,flags):
        #print("open reached:",path,flags)
        self.fd+=1
        return self.fd

    def read(self,path,size,offset,fh):
        #print("read")
        session=Session()
        f=getFileFromPath(path,session)
        if not f: return ""
        #print(":-:-:",f.data[offset:offset+size])
        #return f.data[offset:offset+size]
        data=bytes()
        blockoffs=offset//self.blocksize
        offset=offset%self.blocksize
        while size >0:
            #print(data)
            if blockoffs>=len(f.data): break
            data+=f.data[blockoffs].datum[offset:min(self.blocksize,size+offset)]
            size-=(self.blocksize-offset)
            blockoffs+=1
            offset=0
            #print("Loop!")
        #print(len(data))
        #print(data)
        #print(data.decode())
        return data

    def write(self,path,data,offset,fh):
        #print("write")
        #print(data)
        #print(type(data))
        session=Session()
        f=getFileFromPath(path,session)
        if not f: return
        #f.data=f.data[:offset]+data
        size=len(data)
        attrs=convertAttr(f.attrs)
        attrs['st_size']=offset+size
        f.attrs=convertAttr(attrs)
        blockoffs=offset//self.blocksize
        offset=offset%self.blocksize
        #print("offset:",offset)
        start=0
        while start<size:
            while blockoffs>=len(f.data):
                f=addBlock(f,session)
            f.data[blockoffs].datum=f.data[blockoffs].datum[:offset]+data[start:start+min(size-start,self.blocksize-offset)]
            start+=min(size-start,self.blocksize-offset)
            offset=0
            blockoffs+=1
            #print("loop!")
        session.commit()
        Session.remove()
        #print(size)
        return size

    def truncate(self, path, length, fh=None):
        #print("truncate")
        session=Session()
        f=getFileFromPath(path,session)
        if not f: return
        #f.data=f.data[:length]
        numblocks=(length+self.blocksize-1)//self.blocksize
        while numblocks>len(f.data):
            f=addBlock(f,session)
        while numblocks>len(f.data):
            f=delBlock(f,session)
        if numblocks>0:
            f.data[-1].datum=f.data[-1].datum[:length%self.blocksize]
        attrs=convertAttr(f.attrs)
        attrs['st_size']=length
        f.attrs=convertAttr(attrs)
        session.commit()
        Session.remove()

    def utimens(self, path, times=None):
        now=time()
        atime, mtime = times if times else (now,now)
        session=Session()
        f=getFileFromPath(path,session)
        if not f: return
        attrs=convertAttr(f.attrs)
        attrs['st_atime']=atime
        attrs['st_mtime']=mtime
        f.attrs=convertAttr(attrs)
        session.commit()
        Session.remove()

    def rmdir(self,path):
        session=Session()
        rmByPath(path,session)
        session.commit()
        Session.remove()

    def unlink(self, path):
        session=Session()
        rmByPath(path,session)
        session.commit()
        Session.remove()

    def rename(self, old, new):
        session=Session()
        #pieces=set(new.split('/')[:-1])
        '''
        npieces=set()
        for p in pieces:
            if len(p)<2:continue
            if p[0]=='!':
                npieces.add(p)
        pieces-=npieces
        npieces=list(npieces)
        for i in range(len(npieces)):
            npieces[i]=npieces[i][1:]
        new='/'+'/'.join(pieces)
        nnew='/'+'/'.join(npieces)
        tags=getTagsFromPath(new,session)
        ntags=getTagsFromPath(nnew,session)
        '''
        tags=getTagsFromPath_logical(new,session)
        f=getObjByPath(old,session)
        f.tags-=set(tags[1])
        f.tags|=set(tags[0])
        session.commit()
        Session.remove()

    def readlink(self, path):
        return self.read(path,float("inf"),0,None)

if __name__ == "__main__":
    if len(argv) < 2:
        print('usage: %s <mountpoint> [database]' % argv[0])
        exit(1)
    fuse = FUSE(STUFFS(), argv[1], foreground=True)

