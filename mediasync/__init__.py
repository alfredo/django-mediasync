from django.conf import settings
from mediasync.utils import load_backend, cssmin, jsmin
import os
import re

JS_MIMETYPES = (
    "application/javascript",
    "text/javascript", # obsolete, see RFC 4329
)
CSS_MIMETYPES = (
    "text/css",
)
TYPES_TO_COMPRESS = (
    "application/json",
    "application/xml",
    "text/html",
    "text/plain",
    "text/xml",
) + JS_MIMETYPES + CSS_MIMETYPES

def client():
    backend_name = getattr(settings, "MEDIASYNC", {}).get("BACKEND", None)
    return load_backend(backend_name)

def listdir_recursive(dir):
    for root, dirs, files in os.walk(dir):
        basename = os.path.basename(root)
        if not (basename.startswith('.') or basename.startswith('_')):
            for file in files:
                fname = os.path.join(root, file).replace(dir, '', 1)
                if fname.startswith('/'):
                    fname = fname[1:]
                yield fname
        else:
             pass # "Skipping directory %s" % root

def sync(bucket=None, prefix=''):
    """ Let's face it... pushing this stuff to S3 is messy.
        A lot of different things need to be calculated for each file
        and they have to be in a certain order as some variables rely
        on others.
    """
    
    from django.conf import settings
    from mediasync.backends import s3
    import cStringIO
    
    assert hasattr(settings, "MEDIA_ROOT")
    
    CSS_PATH = getattr(settings, "MEDIASYNC_CSS_PATH", "").strip('/')
    JS_PATH = getattr(settings, "MEDIASYNC_JS_PATH", "").strip('/')
        
    # check for bucket and prefix parameters
    
    if not bucket:
        bucket = getattr(settings, "MEDIASYNC_AWS_BUCKET", None)
        if not bucket:
            raise ValueError("bucket is required")
            
    if not prefix:
        prefix = getattr(settings, "MEDIASYNC_AWS_PREFIX", '').strip('/')
    
    # construct media url
    bucket_cname = getattr(settings, "MEDIASYNC_BUCKET_CNAME", False)
    media_url = (bucket_cname and "http://%s" or "http://%s.s3.amazonaws.com") % bucket
    if prefix:
        media_url = "%s/%s" % (media_url, prefix)
    
    # create s3 connection
    client = s3.Client(settings.MEDIASYNC_AWS_KEY, settings.MEDIASYNC_AWS_SECRET, bucket, prefix)

    #
    # sync joined media
    #
    
    joined = getattr(settings, "MEDIASYNC_JOINED", {})
    
    for joinfile, sourcefiles in joined.iteritems():
        
        joinfile = joinfile.strip('/')
        
        if joinfile.endswith('.css'):
            dirname = CSS_PATH
        elif joinfile.endswith('.js'):
            dirname = JS_PATH
        else:
            continue # bypass this file since we only join css and js
        
        buffer = cStringIO.StringIO()
        
        for sourcefile in sourcefiles:
            
            sourcepath = os.path.join(settings.MEDIA_ROOT, dirname, sourcefile)
            if os.path.isfile(sourcepath):
                f = open(sourcepath)
                buffer.write(f.read())
                f.close()
                buffer.write('\n')        
        
        filedata = buffer.getvalue()
        buffer.close()
        
        s3filepath = prefix
        if dirname:
            s3filepath = "%s/%s" % (s3filepath, dirname)
        s3filepath = "%s/%s" % (s3filepath, joinfile)
        
        _sync_file(client, joinfile, s3filepath, filedata)
        
    #
    # sync static media
    #

    for dirname in os.listdir(settings.MEDIA_ROOT):
        
        dirpath = os.path.abspath(os.path.join(settings.MEDIA_ROOT, dirname))
        
        if os.path.isdir(dirpath):
           
            for filename in listdir_recursive(dirpath):
                
                # calculate local and remote paths
                filepath = os.path.join(dirpath, filename)
                s3filepath = "%s/%s/%s" % (prefix, dirname, filename)
                
                if filename.startswith('.') or not os.path.isfile(filepath):
                    continue # hidden file or directory, do not upload
                
                _sync_file(client, filepath, s3filepath)
                

def _sync_file(client, filepath, remote_path, filedata=None):
    
    from django.conf import settings
    import mimetypes
                
    # load file data from local path
    if not filedata:
        filedata = open(filepath, 'rb').read()
    
    # guess the content type
    content_type = mimetypes.guess_type(filepath)[0]
    if not content_type:
        content_type = "text/plain"

    # check to see if cssmin or jsmin should be run
    if content_type in CSS_MIMETYPES:
        filedata = cssmin.cssmin(filedata)
    elif content_type in JS_MIMETYPES:
        filedata = jsmin.jsmin(filedata)
    
    # rewrite CSS if the user chooses
    if getattr(settings, "MEDIASYNC_REWRITE_CSS", False): 
        if content_type == "text/css" or filepath.endswith('.htc'):
            MEDIA_URL_RE = re.compile(r"/media/\w+/")
            filedata = MEDIA_URL_RE.sub(r'%s/\1/' % media_url, filedata)
    
    if client.put(filedata, content_type, remote_path):
        print "[%s] %s" % (content_type, remote_path)

__all__ = ['MEDIA_URL','sync']
