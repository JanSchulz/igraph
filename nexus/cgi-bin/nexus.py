#! /bin/env /home/csardi/software/bin/mypython
# vim:set ts=4 sw=4 sts=4 et

import sys
sys.path.append("../python")

import web
import model
import math
import random
import os
import url_helper
import odict
import subprocess
import markdown
import igraph
import xlwt
import xlrd
import pickle
import re
import tempfile
import gzip
import shutil
import hashlib
import sqlite3

from datetime import datetime
from functools import wraps
from itertools import izip, chain
from operator import attrgetter
from recaptcha.client import captcha
from textwrap import dedent

httpsserver = 'secure1298.hostgator.com'
httpshome = '/~csardi/nexus'

web.config.debug = False
web.config.smtp_server = '173.192.111.8'
web.config.smtp_port = 26
web.config.smtp_username = 'csardi@mail.igraph.org'
web.config.smtp_password = \
    file(os.path.join("..", "config", "emailpass")).read().strip()
web.config.smtp_starttls = True

formwidth=65
datadir=os.path.join("..", "data")

urls = (
    '/?',                                  'About',
    '/api/dataset_info',                   'Index',
    '/api/dataset',                        'Dataset',
    '/api/format',                         'Format',
    '/api/licence',                        'Licence',
    '/api/search',                         'Search',
    '/web/about',                          'About',
    '/web/addblog',                        'AddBlog',
    '/web/addlicence',                     'AddLicence',
    '/web/add',                            'Add',
    '/web/admin',                          'Admin',
    '/web/blog',                           'Blog',
    '/web/checkall2',                      'Check',
    '/web/checkall',                       'CheckAll',
    '/web/check/(\d+)',                    'Check',
    '/web/delete/(\d+)',                   'Delete',
    '/web/docs',                           'Docs',
    '/web/donate',                         'Donate',
    '/web/editblog/(\d+)',                 'EditBlog',
    '/web/editlicence/(\d+)',              'EditLicence',
    '/web/edit/(\d+)',                     'Edit',
    '/web/feedback',                       'Feedback',
    '/web/recreateall/(.+)',               'RecreateAll',
    '/web/recreate/(\d+)',                 'Recreate',
    '/web/updatefilesize',                 'UpdateFilesize',
    '/web/search',                         'Searchpage',
    '/web/login',                          'Login',
    '/web/logout',                         'Logout',
    '/error/(\d+)',                        'Error',
    '.*',                                  'Error'
    )

# reCAPTCHA keys
recaptcha_pubkey = "6Lfqjb8SAAAAAJyGZQrvqgs7JWjpNp_Vf9dpTMxy"

# Text to be included in the HTML output whenever a reCAPTCHA is needed
recaptcha_text = """
<div class="recaptcha">
<script type="text/javascript">
   var RecaptchaOptions = {
      theme : 'white'
   };
</script>
<script type="text/javascript"
        src="http://www.google.com/recaptcha/api/challenge?k=%s">
</script>
<noscript>
  <iframe src="http://www.google.com/recaptcha/api/noscript?k=%s"
          height="300" width="500" frameborder="0"></iframe><br>
  <textarea name="recaptcha_challenge_field" rows="3" cols="40">
  </textarea>
  <input type="hidden" name="recaptcha_response_field"
         value="manual_challenge">
</noscript>
</div>
""" % (recaptcha_pubkey, recaptcha_pubkey)

# List of supported webpage formats
formats = ('html', 'xml', 'text', 'rss', 'atom')

def unique(seq):
    # Not order preserving
    keys = {}
    for e in seq:
        keys[e] = 1
    return keys.keys()

def get_current_url():
    """Returns the URL of the current page being produced"""
    return web.ctx.fullpath

def get_whatsnew():
    """Retrieves the new datasets from the model and renders it."""
    w=model.whatsnew()
    return render_plain.whatsnew(w)

def get_datatags():
    """Retrieves the list of tags and tag counts in the model and renders a
    nice tag cloud."""
    tags = [tag for tag in model.datatags()]
    counts = [tag.count for tag in tags]
    max_count = max(counts)
    sizes = [ int(math.log(count+1) / math.log(max_count+1) * 5) for count in counts]
    for tag, size in izip(tags, sizes):
        tag.count = size
    tags.sort(key = attrgetter("tag"))
    return render_plain.datatags(tags)

def mymarkdown(text, limit=4):
    if text.count("\n") <= limit:
        return markdown.markdown(text)
    else:
        res="\n".join(text.split("\n")[0:limit])
        return markdown.markdown(res) + '&hellip;'

def get_motto():
    tot=model.get_totals()
    if tot.downloads is not None:
        return "%s data sets, downloaded %s times" % (tot.count, tot.downloads)
    return "%s data sets" % tot.count

def get_available_formats(id, sid=None):
    """Data formats that are available for a given data set"""
    allf=model.get_formats()
    fname=model.get_dataset_filename(id)
    def fileexists(formatrec, filename, sid):
        if sid is None:
            ff=os.path.join(datadir, id, filename + formatrec.extension)
        else:
            ff=os.path.join(datadir, id, filename + "-" + sid + 
                            formatrec.extension)
        if os.path.isfile(ff):
            return os.path.getsize(ff)
        else:
            return 0
    tests=[ (f, fileexists(f, fname, sid)) for f in allf ]
    tests=[ f for f in tests if f[1] ]
    for i in enumerate(tests):
        tests[i[0]][0].size=tests[i[0]][1]
    return dict( (f[0].name, f[0]) for f in tests)

def make_link(keys, **extra):
    def ex(k,v):
        if k in extra:
            return (k, extra[k])
        else:
            return (k,v)
    args=[ '%s=%s' % ex(k,v) for k, v in keys.items() if v is not None ]
    return "?" + "&".join(args)

def getbase():
    servername = web.ctx.environ['SERVER_NAME']
    if servername == httpsserver:
        return httpshome
    else:
        return ''

## TODO: what if there are too many pages. Currently not a problem,
## only if we'll have hundreds of data sets.
def prevnexttable(nohits, start, end, limit, user_input):

    start=int(start)
    end=int(end)
    limit=int(limit)

    prevtext='<span class="prevpage">&lt;&lt;</span>'
    nexttext='<span class="nextpage">&gt;&gt;</span>'

    if start == 1:
        prev=prevtext
    else:
        prev='<a href="%s">%s</a>' % (make_link(user_input, 
                                                offset=start-limit-1),
                                      prevtext)

    if start+limit < nohits:
        next='<a href="%s">%s</a>' % (make_link(user_input, 
                                                offset=start+limit-1),
                                      nexttext)
    else:
        next=nexttext
    
    if limit==0:
        pages=0
        actual=0
    else:
        pages=int(math.ceil(float(nohits) / limit))
        actual=int(math.ceil(float(start) / limit))

    pagelinks=[ '<a href="%s">%s</a>' % (make_link(user_input,
                                                   offset=n*limit), n+1) 
                for n in range(pages) ]
    if actual != 0:
        pagelinks[actual-1] = '<span class="actualpage">%s</span>' % (actual)

    return prev + " " + " ".join(pagelinks) + " " + next

def makelinks(text):
    return re.sub(r'(http://[^ \n\t]+)', r'<a href="\1">\1</a>', text)

def redirect_to(location):
    headers = { 
        'Content-Type': 'text/html',
        'Location': location
        }
    raise web.HTTPError("303 See Other", headers, "")
    
def errorpage():
    error_url = web.ctx.protocol + '://' + web.ctx.host + \
        getbase() + '/error/404'
    redirect_to(error_url)

def redirect_to_main():
    redirect_to(web.ctx.protocol + '://' + web.ctx.host + getbase())

def check_admin(redirect=True):
    '''Check if the current user is authenticated and admin.
    If a redirect is requested, then we redirect to a 404 page.'''

    safe = check_safe(redirect=redirect)
    if not safe:
        if redirect:
            errorpage()
        else:
            return False
    else:
        if session.loggedin and session.admin:
            return True
        else:
            if redirect:
                errorpage()
            else:
                return False

def check_loggedin():
    if not check_safe(redirect=False):
        return False
    return session.loggedin

def check_safe(redirect=True):
    '''Check whether we are on HTTPS or connecting locally.
    If a redirect is requested, then we redirect to a 404 page.'''

    good = web.ctx.protocol == "https" or \
        web.ctx.environ['REMOTE_ADDR'] == '127.0.0.1'
    if not good and redirect:
        errorpage()

    return good

def pretty_size(bytes):
    if bytes < 10**3:
        return str(bytes) + ' bytes'
    elif bytes < 10**6:
        return str(round(bytes/(10**3.0),1)) + ' Kbytes'
    elif bytes < 10**9:
        return str(round(bytes/(10**6.0),1)) + ' Mbytes'
    else:
        return str(round(bytes/(10**9.0),1)) + ' Gbytes'

add_form=web.form.Form(
    web.form.Textbox("sid", description="Id:", id="focused", size=formwidth),
    web.form.Textbox("name", description="Name:", size=formwidth),
    web.form.Textarea("shortdescription", description="Short description:",
                      rows=5, cols=formwidth),
    web.form.Textarea("description", description="Description:",
                      rows=10, cols=formwidth),
    web.form.Textbox("tags", description="Tags:",
                     post="<br/> (comma separated)", size=formwidth),
    web.form.Dropdown("licence", description="Licence:", args=[]),
    web.form.Textbox("source", description="Source:", size=formwidth),
    web.form.Textarea("papers", description="Publication(s):", 
                      rows=8, cols=formwidth)
    )

def add_net_form(no):
    return web.form.Form(
        web.form.Textbox("net%ssid" % no, description="Id:", size=formwidth),
        web.form.Textbox('net%svertices' % no, description='Vertices:', 
                         size=formwidth),
        web.form.Textbox('net%sedges' % no, description='Edges:', 
                         size=formwidth),
        web.form.Textbox('net%sfilename' % no, description='Filename:', 
                         size=formwidth),
        web.form.Checkbox("net%sdirected" % no, description="Directed:", 
                          value="True"),
        web.form.Checkbox("net%sweighted" % no, description="Weighted:", 
                          value="True"),
        web.form.Checkbox("net%sbipartite" % no, description="Bipartite:", 
                          value="True"),
        web.form.Textarea('net%sdescription' % no,  rows=5, cols=formwidth,
                          description="Short description:"),
        web.form.Button('Delete network', 
                        onClick="delNet('%s'); return false;" % no)
        )

def add_meta_form(no):
    return web.form.Form(
        web.form.Textbox("meta%sname" % no, description="Name:", 
                         size=formwidth),
        web.form.Dropdown("meta%stype" % no, description="Type:", 
                          args=['graph', 'vertex', 'edge']),
        web.form.Dropdown("meta%sdatatype" % no, description="Datatype:",
                          args=['numeric', 'string', 'logical']),
        web.form.Textbox("meta%snetwork" % no, description="Network:", 
                         size=formwidth),
        web.form.Textarea("meta%sdescription" % no, 
                          description="Short description:", 
                          rows=5, cols=formwidth),
        web.form.Button('Delete attribute',
                        onClick="delMeta('%s'); return false;" % no)
        )

tempglob = { 'dataformats': model.get_format_extensions(),
             'getusername': model.get_username,
             'currenturl': get_current_url,
             'get_whatsnew': get_whatsnew,
             'get_datatags': get_datatags,
             'get_motto': get_motto,
             'mymarkdown': mymarkdown,
             'markdown': markdown.markdown,
             'type': type,
             'prevnexttable': prevnexttable,
             'add_net_form': add_net_form,
             'add_meta_form': add_meta_form,
             'check_admin': check_admin,
             'makelinks': makelinks,
             'getbase': getbase,
             'check_safe': check_safe,
             'check_loggedin': check_loggedin,
             'pretty_size': pretty_size }

for name in url_helper.__all__:
    tempglob[name] = getattr(url_helper, name)

render = web.template.render('templates', base='base', globals=tempglob)
render_plain = web.template.render('templates', globals=tempglob)

class Donate:
    """Handler class for the "Donate data" page."""

    donate_form=web.form.Form(
        web.form.Textbox("name", description="Your name:", id="focused"),
        web.form.Textbox("email", description="Your email address:"),
        web.form.Textbox("url", description="FTP or Web URL:"),
        web.form.Checkbox("directed", description="Directed:", 
                          value="True"),
        web.form.Checkbox("weighted", description="Weighted:",
                          value="True"),
        web.form.Checkbox("bipartite", description="Two-mode:",
                          value="True"),
        web.form.Checkbox("dynamic", description="Dynamic:", 
                          value="True"),
        web.form.Textbox("tags", description="Tags:"),
        web.form.Dropdown("licence", description="Licence:", args=[]),
        web.form.Textarea("description", 
                          description="Data format description:", 
                          cols=formwidth, rows=10),
        web.form.Textarea("papers", description="Publication(s):", 
                          cols=formwidth, rows=10),
        web.form.Button("Donate!", pre=recaptcha_text)
        )
    
    def GET(self):
        form=self.donate_form()
        lic=model.get_licences('id,name')
        form.licence.args=[(l.id,  l.name) for l in lic]        
        return render.donate(form, False, False, False)

    def POST(self):
        form=self.donate_form()
        if not form.validates():
            ## TODO
            None
        
        user_input=web.input()
        recaptcha_private_key = \
            file(os.path.join("..", "config", 
                              "recaptcha_private_key")).read().strip()
        valid=captcha.submit(user_input.recaptcha_challenge_field,
                             user_input.recaptcha_response_field,
                             recaptcha_private_key,
                             web.ctx.ip)

        if not valid.is_valid:
            return render.donate(form, True, False, False)

        try:
            web.sendmail('nexus@igraph.org', 'nexus@igraph.org', 
                         'Nexus donation', 
                         'Name:        ' + form.d.name        + '\n'   +
                         'Email:       ' + form.d.email       + '\n'   +
                         'URL:         ' + form.d.url         + '\n'   +
                         'Directed:    ' + str(form.d.directed) + '\n' + 
                         'Weighted:    ' + str(form.d.weighted) + '\n' +
                         'Bipartite:   ' + str(form.d.bipartite)+ '\n' + 
                         'Dynamic:     ' + str(form.d.dynamic)  + '\n' + 
                         'Tags:        ' + form.d.tags        + '\n'   + 
                         'Licence:     ' + form.d.licence     + '\n\n' + 
                         'Description: ' + form.d.description + '\n\n' +
                         'Publication: ' + form.d.papers      + '\n\n')
            return render.donate(form, True, True, True)
        except:
            return render.donate(form, True, True, False)

class About:
    """Renders the contents of the About page."""

    def GET(self):
        return render.about()

class Feedback:
    """Renders the feedback form."""

    feedback_form = web.form.Form(
        web.form.Textbox("name", description="Your name (optional):"),
        web.form.Textbox("email", description="Your email (optional):"), 
        web.form.Textarea("message", description="Your message:", 
                          cols=formwidth, rows=10),
        web.form.Button("Send message", pre=recaptcha_text)
        )

    def GET(self):
        form=self.feedback_form()
        return render.feedback(form)

    def POST(self):
        form=self.feedback_form()
        if not form.validates():
            ## TODO
            pass

        user_input=web.input()
        recaptcha_private_key = \
            file(os.path.join("..", "config",
                              "recaptcha_private_key")).read().strip()
        valid=captcha.submit(user_input.recaptcha_challenge_field,
                             user_input.recaptcha_response_field,
                             recaptcha_private_key,
                             web.ctx.ip)

        if not valid.is_valid:
            return render.feedback_ok(form, False, False)

        try:
            web.sendmail('nexus@igraph.org', 'nexus@igraph.org', 
                         'Nexus feedback', 
                         form.d.message + "\n\nEmail:" + form.d.email)
            return render.feedback_ok(form, True, True)
        except Exception, x:
            return render.feedback_ok(form, True, False)

class Index:
    """Renders the index page."""

    def list_datasets(self, user_input):
        format=user_input.format

        datasets, co=list(model.get_list_of_datasets(order=user_input.order,
                                                    limit=user_input.limit,
                                                    offset=user_input.offset))
        ids=[d.id for d in datasets]
        tags={}
        for i in ids:
            tags[i] = list(model.get_tags(i))

        if format=='html':
            feed=getbase() + '/api/dataset_info?format=atom'
            return render.index(datasets, tags, "All data sets", feed,
                                co, int(user_input.offset)+1, 
                                int(user_input.offset)+len(datasets), 
                                int(user_input.limit), user_input, None)
        elif format=='xml':
            networks={}
            for i in ids:
                networks[i] = model.get_networks(i)
            web.header('Content-Type', 'text/xml')
            return render_plain.xml_index(datasets, tags,
                                          len(datasets), co,
                                          int(user_input.offset),
                                          int(user_input.limit),
                                          'All data sets', networks)
        elif format=='text':
            for k, t in tags.iteritems():
                tags[k]=";".join(x.tag for x in t)
            networks={}
            for i in ids:
                networks[i] = model.get_networks(i)
            web.header('Content-Type', 'text/plain')
            return render_plain.text_index(datasets, tags,
                                           len(datasets), co,
                                           int(user_input.offset),
                                           int(user_input.limit),
                                           'All data sets', networks)
        elif format=='rss':
            date=datetime.today().strftime("%a, %d %b %Y %H:%M:%S +0200")
            web.header('Content-Type', 'application/rss+xml')
            return render_plain.rss_index(datasets, tags, 
                                          "All data sets", 
                                          date, web.ctx.homedomain, getbase())
        elif format=='atom':
            date=datetime.today().strftime("%a, %d %b %Y %H:%M:%S +0200")
            web.header('Content-Type', 'application/atom+xml')
            return render_plain.atom_index(datasets, tags, 
                                           "All data sets", 
                                           date, web.ctx.homedomain, 
                                           getbase())

    def format_text(self, dataset, tags, meta, formats, papers):

        def format_attr(attr):
            return "attribute: %s %s %s\n  %s" % \
                (attr.type, attr.datatype, attr.name, attr.description)

        nets=model.get_networks(dataset.id)
        networks=" ".join([ "%s/%s" % (n.id, n.sid) for n in nets ])
        vertedges=" ".join([ "%s/%s" % (n.vertices, n.edges) for n in nets ])

        tags=";".join([x.tag for x in tags])
        papers=[p.citation.replace("\n", "\n  ").strip() for p in papers]
        papers="\n  ".join(papers)
        desc=dataset.description.replace("\n\r\n", "\n.\n")
        desc=desc.replace("\n", "\n  ").strip()
        main=dedent("""\
                id: %i
                sid: %s
                name: %s
                networks: %s
                vertices/edges: %s
                tags: %s
                date: %s
                licence: %s
                licence url: %s
                summary: %s
                description: %s
                formats: %s
                citation: %s""") % \
                (dataset.id, dataset.sid, dataset.name, networks, 
                 vertedges, tags, dataset.date[0:10],
                 dataset.licence_name, dataset.licence_url,
                 dataset.shortdescription.replace("\n", "\n  ").strip(),
                 desc, ";".join(n+'('+str(v.size)+')' 
                                for n,v in formats.items()),
                 papers)
        meta="\n".join(format_attr(m) for m in meta)
        if meta != "": meta = "\n" + meta
        return main + meta

    def dataset(self, user_input):
        id=user_input.id
        if not re.match('^[0-9]+$', id):
            id=model.get_id_from_sid(id)

        if id is None:
            return web.notfound()

        format=user_input.format
        dataset=[d for d in model.get_dataset(id)][0]
        if not dataset:
            return web.notfound()        
        tags=list(model.get_tags(id))
        meta=list(model.get_metadata(id))
        formats=get_available_formats(id)
        papers=list(model.get_papers(id))
        networks=model.get_networks(id)

        if format=='html':
            return render.dataset(dataset, tags, meta, formats, papers, 
                                  networks)
        elif format=='xml':
            networks=model.get_networks(id)
            web.header('Content-Type', 'text/xml')
            return render_plain.xml_dataset(dataset, tags, meta,
                                            formats, papers, networks)
        elif format=='text':
            formatted=self.format_text(dataset, tags, meta, formats, papers)
            web.header('Content-Type', 'text/plain')
            return render_plain.text_dataset(formatted)

    def list_tagged(self, user_input):
        tagname=user_input.tag.split("|")
        format=user_input.format
        if user_input.operator not in ("and", "or"):
            return web.notfound()
        datasets, co=list(model.get_list_tagged_as(tagname,
                                                   user_input.operator, 
                                                   limit=user_input.limit,
                                                   offset=user_input.offset))
        ids=[d.id for d in datasets]
        tags={}
        for i in ids:
            tags[i] = list(model.get_tags(i))

        tagname=["'%s'" % t for t in tagname]
        tagname=(" " + user_input.operator + " ").join(tagname)

        if format=='html':
            feed=getbase() + \
                '/api/dataset_info?format=atom&tag=%s&operator=%s' % \
                (user_input.tag, user_input.operator)
            return render.index(datasets, tags, 
                                "Data sets tagged %s" % tagname, feed,
                                co, int(user_input.offset)+1, 
                                int(user_input.offset)+len(datasets),
                                int(user_input.limit), user_input, None)
        elif format=='xml':
            networks={}
            for i in ids:
                networks[i] = model.get_networks(i)
            web.header('Content-Type', 'text/xml')
            return render_plain.xml_index(datasets, tags, 
                                          len(datasets), co,
                                          int(user_input.offset),
                                          int(user_input.limit),
                                          "Data sets tagged %s" 
                                          % tagname, networks)
        elif format=='text':
            for k,t in tags.items():
                tags[k]=";".join([x.tag for x in t])
            networks={}
            for i in ids:
                networks[i] = model.get_networks(i)
            web.header('Content-Type', 'text/plain')
            return render_plain.text_index(datasets, tags, 
                                           len(datasets), co,
                                           int(user_input.offset),
                                           int(user_input.limit),
                                           "Data sets tagged '%s'" 
                                           % tagname, networks)
        elif format=="rss":
            date=datetime.today().strftime("%a, %d %b %Y %H:%M:%S +0200")
            web.header('Content-Type', 'application/rss+xml')
            return render_plain.rss_index(datasets, tags, 
                                          "Nexus data sets tagged %s" 
                                          % tagname, date,
                                          web.ctx.homedomain, 'tagged/%s' 
                                          % tagname)
        elif format=="atom":
            date=datetime.today().strftime("%a, %d %b %Y %H:%M:%S +0200")
            web.header('Content-Type', 'application/atom+xml')
            return render_plain.atom_index(datasets, tags, 
                                           "Nexus data sets tagged %s" 
                                           % tagname, date,
                                           web.ctx.homedomain, 'tagged/%s' 
                                           % tagname)        

    def GET(self):
        user_input=web.input(format="html", id=None, tag=None,
                             operator="or", order="date", offset=0,
                             limit=10)
        if user_input.order not in ('date', 'name', 'popularity'):
            return web.notfound()
        if user_input.tag is not None and user_input.id is not None:
            return web.notfound()
        if user_input.id is not None:
            return self.dataset(user_input)
        elif user_input.tag is not None:
            return self.list_tagged(user_input)
        else:
            return self.list_datasets(user_input)

def support_gzip():
    if 'HTTP_ACCEPT_ENCODING' not in web.ctx.environ:
        return False
    else:
        enc=web.ctx.environ['HTTP_ACCEPT_ENCODING']
        encodings = [ e.strip() for e in enc.split(",") ]
        return 'gzip' in encodings or 'x-gzip' in encodings

class Dataset:
    
    def GET(self):
        user_input=web.input(id=None)
        format=user_input.format

        if user_input.id is None:
            return web.notfound()
        
        if re.match('^[0-9]+.?[0-9]*$', user_input.id):
            id=user_input.id.split(".")
            if len(id)==1:
                id=id[0]
                subid=None
            else:
                id=id[0]
                subid=id[1]
        else:
            sid=user_input.id.split(".", 1)
            if len(sid)==1:
                id=model.get_id_from_sid(sid[0])
                subid=None
            else:
                id=model.get_id_from_sid(sid[0])
                subid=model.get_netid_from_netsid(sid[1])

        if id is None:
            return web.notfound()

        datafile=model.get_dataset_filename(id)

        if not datafile:
            return web.notfound()

        basename=datafile
        ext=model.get_format_extension(format)
        filename=os.path.join(datadir, id, basename + ext)
        web.header('Content-Type', 'application/octet-stream')
        web.header('Content-Disposition', 
                   'attachment; filename="%s%s"' % (basename,ext))
        model.increase_downloads(id)
        try:
            f=open(filename)
            data=f.read()
            f.close()
            return data
        except Exception, x:
#            print str(x)
            return web.notfound()

class Format:

    def format_one(self, format):
        return """Name: %s
Short description: %s
Description: %s
URL: %s""" % (format.name, format.shortdesc, 
              format.description.replace("\n\r\n", "\n  .\n").strip(),
              format.link)

    def format_text(self, formats):
        return "\n\n".join([ self.format_one(f) for f in formats ])

    def GET(self):
        user_input=web.input(format="html", dataformat=None)
        format=user_input.format
        dataformat=user_input.dataformat

        if dataformat:
            data=[d for d in model.get_format(dataformat)]
            if not data:
                return web.notfound()
        else:
            data=[d for d in model.get_formats()]

        if format=='html':
            return render.format(data)
        elif format=='xml':
            web.header('Content-Type', 'text/xml')
            return render_plain.xml_formats(data)
        elif format=='text':
            formatted=self.format_text(data)
            web.header('Content-Type', 'text/plain')
            return render_plain.text_formats(formatted)

class Add:

    def GET(self):
        check_admin()
        form=add_form()
        lic=model.get_licences('id,name')
        form.licence.args=[(l.id,  l.name) for l in lic]
        return render.add(form, False, False, None)
    
    def POST(self):
        check_admin()
        form=add_form()
        input=web.input()
        form.validates()

        ## TODO: validate

        ## data set
        did=model.new_dataset(sid=input['sid'], name=input['name'].strip(),
                              shortdescription=\
                                  input['shortdescription'].strip(),
                              description=input['description'].strip(),
                              licence=int(input['licence']),
                              source=input['source'].strip(),
                              date=web.SQLLiteral("CURRENT_DATE"),
                              downloads=0)
        
        ## tags
        if input['tags']=="":
            tags=[]
        else:
            tags=[t.strip() for t in input['tags'].split(",")]

        ## network(s)
        netids=[ int(n[3:][:-3]) for n in input.keys() if 
                 re.match('^net[0-9]+sid$', n) is not None ]
        for i, no in enumerate(netids):
            directed=('net%sdirected' % no) in input
            if directed and 'directed' not in tags:
                tags.append('directed')
            if not directed and 'undirected' not in tags:
                tags.append('undirected')
            weighted=('net%sweighted' % no) in input
            if weighted and 'weighted' not in tags:
                tags.append('weighted')
            bipartite=('net%sbipartite' % no) in input
            if bipartite and 'bipartite' not in tags:
                tags.append('bipartite')
            model.new_network(dataset=did, id=i+1, 
                              sid=input['net'+str(no)+'sid'].strip(),
                              description=\
                                  input['net'+str(no)+'description'].strip(),
                              vertices=int(input['net'+str(no)+'vertices']),
                              edges=int(input['net'+str(no)+'edges']),
                              filename=input['net'+str(no)+'filename'],
                              date=web.SQLLiteral("CURRENT_DATE"),
                              directed=directed, weighted=weighted,
                              bipartite=bipartite)

        ## citations
        cits=input['papers'].split("\r\n\r\n")
        for cit in cits:
            model.new_citation(dataset=did, citation=cit.strip())
            
        ## add the tags
        for tag in tags:
            model.new_dataset_tag(dataset=did, tag=tag.strip())
        
        ## attributes
        netnames=[ input['net%ssid' % no] for no in netids ]
        attrids=[ int(n[4:][:-4]) for n in input.keys() if 
                  re.match('^meta[0-9]+name$', n) ]
        for no in attrids:
            netname=input['meta%snetwork' % no]
            if netname == "":
                net=web.db.sqlify(None)
            else:
                net=netnames.index(input['meta%snetwork' % no])
            model.add_meta(id=did, network=net,
                           type=input['meta%stype' % no],
                           name=input['meta%sname' % no],
                           datatype=input['meta%sdatatype' % no],
                           description=\
                               input['meta%sdescription' % no].strip())

        return render.add(form, True, False, did)

class Edit:
    
    def GET(self, id):
        check_admin()
        form=add_form()
        lic=model.get_licences('id,name')
        form.licence.args=[(l.id,  l.name) for l in lic]
        
        ds=list(model.get_dataset(id))[0]
        form.fill(ds)
        papers=[p.citation for p in model.get_papers(id)]
        form.papers.value="\n\n".join(papers)
        tags=set(t.tag for t in model.get_tags(id))
        tags -= set(("weighted", "bipartite", "directed", "undirected"))
        form.tags.value=", ".join(sorted(tags))
        
        nets=model.get_networks(id)
        def netform(no, net):
            f=add_net_form(no)()
            f['net%ssid' % no].set_value(net.sid)
            f['net%svertices' % no].set_value(net.vertices)
            f['net%sedges' % no].set_value(net.edges)
            f['net%sfilename' % no].set_value(net.filename)
            f['net%sdirected' % no].set_value(net.directed)
            f['net%sweighted' % no].set_value(net.weighted)
            f['net%sbipartite' % no].set_value(net.bipartite)
            f['net%sdescription' %no].set_value(net.description)
            return f
        netforms=[ netform(i+1,n) for i,n in enumerate(nets) ]

        meta=model.get_metadata(id)
        def metaform(no, meta):
            f=add_meta_form(no)()
            f['meta%sname' % no].set_value(meta.name)
            netname=model.get_net_sid_from_id(id, meta.network)
            f['meta%snetwork' % no].set_value(netname)
            f['meta%sdescription' % no].set_value(meta.description)
            f['meta%stype' % no].set_value(meta.type)
            f['meta%sdatatype' % no].set_value(meta.datatype)
            return f
        metaforms=[ metaform(i+1,n) for i,n in enumerate(meta) ]

        return render.add(form, False, True, int(id), netforms, metaforms)

    def POST(self, id):
        check_admin()
        form=add_form()
        input=web.input()
        form.validates()

        # TODO: validate

        if form.d.tags.strip()=="":
            tags=[]
        else:
            tags=[t.strip() for t in form.d.tags.split(',')]

        oldnets=model.get_networks(id)
        oldsids=[ o.sid for o in oldnets ]
        
        netids=[ int(n[3:][:-3]) for n in input.keys() if 
                 re.match("^net[0-9]+sid$", n) is not None ]
        sids=[ input['net%ssid' % no] for no in netids ]
        for i,no in enumerate(sorted(netids)):
            directed=('net%sdirected' % no) in input
            if directed and 'directed' not in tags:
                tags.append('directed')
            if not directed and 'undirected' not in tags:
                tags.append('undirected')
            weighted=('net%sweighted' % no) in input
            if weighted and 'weighted' not in tags:
                tags.append('weighted')
            bipartite=('net%sbipartite' % no) in input
            if bipartite and 'bipartite' not in tags:
                tags.append('bipartite')
            
            sid=input['net%ssid' % no]
            if sid in oldsids:
                model.update_network(dataset=id, 
                                     id=model.get_net_id_from_sid(id, sid),
                                     description=input['net%sdescription' % no],
                                     vertices=input['net%svertices' % no],
                                     edges=input['net%sedges' % no],
                                     filename=input['net%sfilename' % no],
                                     directed=directed,
                                     bipartite=bipartite,
                                     weighted=weighted)
            else:
                model.new_network(dataset=id, sid=sid,
                                  id=model.get_net_id_from_sid(id, sid),
                                  description=input['net%sdescription' % no],
                                  vertices=input['net%svertices' % no],
                                  edges=input['net%sedges' % no],
                                  filename=input['net%sfilename' % no],
                                  directed=directed,
                                  bipartite=bipartite,
                                  weighted=weighted)

        for s in set(oldsids)-set(sids):
            model.delete_network(dataset=id, 
                                 id=model.get_net_id_from_sid(id, s))

        papers=[p.strip() for p in form.d.papers.split("\r\n\r\n")]

        model.update_dataset(id=id, sid=form.d.sid, name=form.d.name, 
                             shortdescription=form.d.shortdescription,
                             description=form.d.description,
                             licence=form.d.licence, 
                             source=form.d.source,
                             papers=papers)

        model.delete_tags(id)
        for t in tags:
            model.new_dataset_tag(dataset=id, tag=t)

        ## Metadata
        oldmeta = model.get_metadata(id)
        for m in oldmeta:
            model.delete_meta(id, m.type, m.name)

        netnames=[ input['net%ssid' % no] for no in netids ]
        attrids=[ int(n[4:][:-4]) for n in input.keys() if 
                  re.match('^meta[0-9]+name$', n) ]
        for no in attrids:
            netname=input['meta%snetwork' % no]
            if netname == "":
                net=web.db.sqlify(None)
            else:
                net=netnames.index(input['meta%snetwork' % no])
            model.add_meta(id=id, network=net,
                           type=input['meta%stype' % no],
                           name=input['meta%sname' % no],
                           datatype=input['meta%sdatatype' % no],
                           description=\
                               input['meta%sdescription' % no].strip())

        return render.add(form, True, True, int(id))

add_licence_form=web.form.Form(
    web.form.Textbox("name", description="Name:", id="focused", size=formwidth),
    web.form.Textarea("text", description="Text:", cols=formwidth, rows=2),
    web.form.Textarea("fulltext", description="Full text:", cols=formwidth, 
                      rows=10),
    web.form.Textbox("link", description="URL:", size=formwidth),
    web.form.Button("Add")
    )

class AddLicence:
    
    def GET(self):
        check_admin()
        form=add_licence_form()
        return render.addlicence(form, False, False, False)

    def POST(self):
        check_admin()
        form=add_licence_form()
        if not form.validates():
            # TODO
            None
            
        lid=model.new_licence(name=form.d.name, text=form.d.text, 
                              fulltext=form.d.fulltext, link=form.d.link)

        return render.addlicence(form, True, False, lid)

class EditLicence:
    def GET(self, id):
        check_admin()
        form=add_licence_form()
        form.Add.name='Submit'
        lic=model.get_licence(id)
        lic=list(lic)[0]
        form.fill(lic)
        return render.addlicence(form, False, False, False)

    def POST(self, id):
        check_admin()        
        form=add_licence_form()
        if not form.validates():
            ## TODO
            pass

        model.update_licence(id=id, name=form.d.name, text=form.d.text,
                             fulltext=form.d.fulltext, link=form.d.link)

        return render.addlicence(form, True, True, int(id))

class Admin:
    def GET(self):
        check_admin()
        return render.admin()

def run_r(cmd):
    Rscript=file(os.path.join("..", "config", "Rscript")).read().strip()
    args=[Rscript, "-e", cmd]
    p=subprocess.Popen(args, stdout=subprocess.PIPE)
    ret=p.wait()
    out=p.stdout.read()
    return [ret, out]

def tmpungzip(filename):
    tmp=tempfile.NamedTemporaryFile(delete=False)
    tmpname=tmp.name
    tmp.close()
    os.system('gzip -cd %s > %s' % (filename, tmpname))
    return tmpname    

class Check:

    def check_r_igraph(self, ds, networks, filename, tags, meta):
        res=odict.odict()

        tagstr=";".join(t.tag for t in tags)
        netnames=";".join(n.sid for n in networks)
        netno=";".join(str(n.id) for n in networks)
        metastr=";;".join("%s;%s;%s" % (m.type, m.name, m.network) 
                          for m in meta)

        rcode=dedent('source("../scripts/rutils.R") ; \
                      r.check("%s","%s","%s","%s","%s") ; \
                     ') % (filename, tagstr, netnames, netno, metastr)
        ret, out=run_r(rcode)
        out=[ o.split(":", 1) for o in out.strip().split("\n") ]
        for k,v in out:
            if v=='TRUE':
                res[k]=True
            else:
                res[k]=v
        v=";".join(str(n.vertices) for n in networks)
        e=";".join(str(n.edges) for n in networks)
        res['Vertices'] = (res['Vertices'] == v)
        res['Edges'] = (res['Edges'] == e)

        return res

    def _check_igraph_graph(self, g, ds, networks, filename, tags, meta):
        res = odict.odict()

        ## Number of vertices and edges
        res['Number of vertices'] = all([ g[n.sid].vcount() == n.vertices
                                          for n in networks ])
        res['Number of edges'] = [ g[n.sid].ecount() == n.edges
                                   for n in networks ]
        
        vattr=dict( (i, j.vs.attribute_names()) for i, j in g.items() )
        eattr=dict( (i, j.es.attribute_names()) for i, j in g.items() )

        print vattr
        print eattr

        ## Tags 
        tags=[t.tag for t in tags]
        if 'directed' in tags:
            res['Tags, directed'] = any(i.is_directed() for i in g.values())
        if 'undirected' in tags:
            res['Tags, undirected'] = any([ not i.is_directed()
                                            for i in g.values()])
        if 'weighted' in tags:
            res['Tags, weighted'] = any(['weight' in e 
                                         for e in eattr.values()])
        if 'bipartite' in tags:
            res['Tags, bipartite'] = any(['type' in v 
                                          for v in vattr.values()])

        ## Metadata
        nets=dict( (n.id, n) for n in networks )
        for m in meta:
            if m.type == "vertex":
                att=vattr
            elif m.type == "edge":
                att=eattr
            if m.network=="NULL":
                res["Metadata, %s, '%s'" % (m.type, m.name)] = \
                    all(m.name in a for a in att.values())
            else:
                res["Metadata, %s, '%s'" % (m.type, m.name)] = \
                    m.name in att[nets[m.network].sid]

        return res

    def check_python_igraph(self, ds, networks, filename, tags, meta):
        res=odict.odict()
        
        ## File exists
        ex=os.path.exists(filename)
        res['Data file exists'] = ex
        if not ex:
            return res

        ## File can be loaded
        try:
            g=pickle.load(gzip.GzipFile(filename))
            res['Data file can be loaded'] = True
        except Exception, x:
#            print str(x)
            res['Data file can be loaded'] = False
            return res

        res.update(self._check_igraph_graph(g, ds, networks, filename, 
                                            tags, meta))
        return res

    def check_graphml(self, ds, networks, filename, tags, meta):
        res=odict.odict()

        ## File exists
        ex=os.path.exists(filename)
        res['Data file exists'] = ex
        if not ex:
            return res

        ## File can be loaded
        try:
            tmp=os.path.join(tempfile.gettempdir(), "nexus")
            shutil.rmtree(tmp, ignore_errors=True)
            os.mkdir(tmp)
            os.system("unzip -d %s %s" % (tmp, filename))
            g=dict((n.sid, igraph.Graph.Read_GraphML('%s/%s.GraphML' % 
                                                     (tmp, n.sid)))
                   for n in networks)
            res['Data file can be loaded'] = True
            shutil.rmtree(tmp)
        except Exception, x:
            print str(x)
            res['Data file can be loaded'] = False
            return res

        res.update(self._check_igraph_graph(g, ds, networks, filename, 
                                            tags, meta))
        return res

    def check_pajek(self, ds, networks, filename, tags, meta):
        res=odict.odict()

        ## File exists
        ex=os.path.exists(filename)
        res['Data file exists'] = ex
        if not ex:
            return res

        ## File can be loaded
        try:
            f=tmpungzip(filename)
            g=igraph.Graph.Read_Pajek(f)
            res['Data file can be loaded'] = True
            os.unlink(f)
        except Exception, x:
#            print str(x)
            res['Data file can be loaded'] = False
            return res

        res.update(self._check_igraph_graph(g, ds, networks, filename, 
                                            tags, meta))
        return res

    def check_excel(self, ds, networks, filename, tags, meta):
        res=odict.odict()

        ## File exists
        ex=os.path.exists(filename)
        res['Data file exists'] = ex
        if not ex:
            return res

        ## File can be loaded
        try:
            f=tmpungzip(filename)
            wb=xlrd.open_workbook(f)
            res['Data file can be loaded'] = True
            os.unlink(f)
        except Exception, x:
            res['Data file can be loaded'] = False
            return res

        ## Number of sheets
        res['Number of sheets'] = wb.nsheets in (2,3)        

        ## Sheet names
        shnames=wb.sheet_names()        
        res['Sheet names'] = shnames[0] == 'Network' and \
            shnames[1] == 'Edges' and shnames[2] == 'Vertices'

        ## Number of vertices and edges
        sh1=wb.sheet_by_index(0)
        res['Number of vertices'] = int(sh1.cell_value(1,1)) == ds.minv
        res['Number of edges'] = int(sh1.cell_value(2,1)) == ds.mine

        ## Tags
        mytags=sh1.row(4)[1:]
        mytags=[ t.value for t in mytags ]
        tags=[ t.tag for t in tags ]
        res['Tags'] = len(set(mytags) & set(tags)) == len(mytags)

        ## Metadata
        sh2=wb.sheet_by_index(1)
        eattr=[ c.value for c in sh2.row(0)[2:] ]
        if wb.nsheets == 3: 
            sh3=wb.sheet_by_index(2)
            vattr=[ c.value for c in sh3.row(0) ]
        else:
            vattr=[]
        for m in meta:
            if m.type == "vertex":
                res["Metadata, vertex, '%s'" % m.name] = m.name in vattr
            elif m.type == "edge":
                res["Metadata, edge, '%s'" % m.name] = m.name in eattr

        return res

    def check(self, ds, networks, format, tags, meta, filename):
        if format=="R-igraph":
            return self.check_r_igraph(ds, networks, filename, tags, meta)
        elif format=="GraphML":
            return self.check_graphml(ds, networks, filename, tags, meta)
        elif format=="Pajek":
            return self.check_pajek(ds, networks, filename, tags, meta)
        elif format=="Excel":
            return self.check_excel(ds, networks, filename, tags, meta)
        elif format=="Python-igraph":
            return self.check_python_igraph(ds, networks, filename, 
                                            tags, meta)
        return None

    def check_all_formats(self, id):
        ds=list(model.get_dataset(int(id)))[0]
        checkres=odict.odict()
        networks=model.get_networks(ds.id)
        tags=list(model.get_tags(ds.id))
        meta=list(model.get_metadata(ds.id))
        for k,v in model.get_format_extensions().items():
            try: 
                if k in ('R-igraph', 'GraphML', 'Python-igraph'):
                    checkres[k] = self.check(ds, networks, k, tags, meta,
                                             os.path.join("..", "data",
                                                          str(id), 
                                                          ds.sid + v))
            except Exception, x:
                checkres[k] = { "Cannot run check": str(x) }

        return checkres

    def GET(self, id=None):
        check_admin()

        if id is None:
            ids=model.get_dataset_ids()
            web.header('Content-type','text/html')
            web.header('Transfer-Encoding','chunked')
            yield ('<html><head><title>Checking datasets...</title>' +
                   '<link rel="stylesheet" href="' + getbase() + \
                       '/static/general.css"' + \
                       'type="text/css"/>' + 
                   '<link rel="icon" type="image/png" href="' + \
                       getbase() + '/static/nexus_logo_black_small.png" />' +
                   '</head><body>')
            for id in ids:
                ds=list(model.get_dataset(id.id))[0]
                yield render_plain.check(id.id, ds,
                                         self.check_all_formats(id.id))
            yield '<h1>Done</h1></body></html>'
        else:
            ds=list(model.get_dataset(id))[0]
            yield render.check(id, ds, self.check_all_formats(id))

class CheckAll:

    def GET(self):
        check_admin()
        return render.checkall()

class Licence:

    def format_text(self, licences):
        
        def format_one(lic):
            return dedent('''\
                     Id: %s
                     Name: %s
                     Short Description: %s
                     URL: %s''' % (lic.id, lic.name, lic.text, lic.link))
        
        return "\n".join(format_one(l) for l in licences)

    def GET(self):
        user_input=web.input(id=None, format="html")
        format=user_input.format

        if user_input.id is None:
            lic=model.get_licences("*")
        else:
            lic=model.get_licence(user_input.id)
        
        if format=='html':
            return render.licence(lic)
        elif format=='xml':
            web.header('Content-Type', 'text/xml')
            return render_plain.xml_licence(lic)
        elif format=='text':
            web.header('Content-Type', 'text/plain')
            return self.format_text(lic)

class Blog:
    
    def GET(self):
        user_input=web.input(id=None, admin=False)
        unpublished = check_admin()
        if user_input.id is None:
            entries=model.get_blog(unpublished=unpublished)
        else:
            entries=model.get_blog(ids=[user_input.id], 
                                   unpublished=unpublished)
        return render.blog(entries, user_input.id)

add_blog_form=web.form.Form(
    web.form.Textbox('title', description='Title:', id='focused', size=formwidth),
    web.form.Textbox('date', description='Date:', size=formwidth),
    web.form.Textarea('entry', description='Text:', rows=20, cols=formwidth),
    web.form.Checkbox('published', description="Published?", value="True"),
    web.form.Button("Add")
    )

class AddBlog:
    
    def GET(self):
        check_admin()
        form=add_blog_form()
        return render.addblog(form, None, added=False, edit=False)

    def POST(self):
        check_admin()
        form=add_blog_form()
        if not form.validates():
            pass
        
        bid=model.new_blog_entry(title=form.d.title, 
                                 date=form.d.date,
                                 entry=form.d.entry,
                                 published=form.d.published)
        
        return render.addblog(form, bid, added=True, edit=False)

class EditBlog:
    
    def GET(self, id):
        check_admin()
        form=add_blog_form()        
        form.Add.name='Submit'
        blog=model.get_blog(ids=[id], unpublished=True)
        form.fill(blog[0])
        return render.addblog(form, id, added=False, edit=True)

    def POST(self, id):
        check_admin()
        form=add_blog_form()
        if not form.validates():
            # TODO
            pass
        
        model.update_blog(id=id, title=form.d.title, date=form.d.date,
                          entry=form.d.entry, published=form.d.published)
        
        return render.addblog(form, id, added=True, edit=True)

class Docs:
    
    def GET(self):
        import docs
        cc=markdown.markdown(docs.docs)
        return render.docs(cc)

class Delete:

    def GET(self, id):
        check_admin()
        model.delete_dataset(int(id))
        return render.delete()

def ungzip(filename):
    os.system('gzip -dc %s > %s' % (filename, filename))

def gzipout(filename):
    os.system('gzip -f %s' % filename)

class RecreateBase:

    def r_to_graphml(self, id):
        nets=model.get_networks(id)
        rext=model.get_format_extension('R-igraph')
        outext=model.get_format_extension('GraphML')
        inputfile = model.get_dataset_filename(id)
        inputfile = os.path.join("..", "data", id, 
                                 os.path.basename(inputfile))
        rcode = dedent('source("../scripts/rutils.R") ; \
                        r.to.graphml("%s%s", "%s%s") ; \
                  ') % (inputfile, rext, inputfile, outext)
        ret, out=run_r(rcode)

    def r_to_pajek(self, id):
        rext=model.get_format_extension('R-igraph')
        outext=model.get_format_extension('Pajek')
        inputfile = model.get_dataset_filename(id)
        inputfile = os.path.join("..", "data", id, 
                                 os.path.basename(inputfile))
        rcode = dedent('source("../scripts/rutils.R") ; \
                        r.to.pajek("%s%s", "%s%s") ; \
                  ') % (inputfile, rext, inputfile, outext)
        ret, out=run_r(rcode)
                           
    def graphml_to_excel(self, id):
        return
        nets=model.get_networks(id)
        if len(nets) > 1:
            return              # TODO
        if nets[0].vertices >= 65536 or nets[0].edges >= 65536:
            return
        inputfile = model.get_dataset_filename(id)
        inputfile = os.path.join("..", "data", id, 
                                 os.path.basename(inputfile))
        graphmlext=model.get_format_extension('GraphML')
        excelext=model.get_format_extension('Excel')
        ungzip('%s%s' % (inputfile, graphmlext))
        g=igraph.Graph.Read_GraphML(inputfile + graphmlext)
        os.unlink('%s%s' % (inputfile, graphmlext))

        ds=list(model.get_dataset(id))[0]
        
        wb=xlwt.Workbook()

        ## The network
        tags=list(model.get_tags(id))
        papers=list(model.get_papers(id))
        sh1=wb.add_sheet('Network')
        sh1.write(0, 0, 'Name')
        sh1.write(0, 1, ds.name)
        sh1.write(1, 0, 'Vertices')
        sh1.write(1, 1, ds.minv)
        sh1.write(2, 0, 'Edges')
        sh1.write(2, 1, ds.mine)
        sh1.write(3, 0, 'Type')
        if 'directed' in tags:
            sh1.write(3, 1, 'directed')
        else:
            sh1.write(3, 1, 'undirected')
        sh1.write(4, 0, 'Tags')
        for n, t in enumerate(tags):
            sh1.write(4, n+1, t.tag)
        sh1.write(5, 0, 'Licence')
        sh1.write(5, 1, ds.licence_name)
        sh1.write(6, 0, 'Licence URL')
        sh1.write(6, 1, ds.licence_url)
        sh1.write(7, 0, 'Short description')
        sh1.write(7, 1, ds.shortdescription)
        sh1.write(8, 0, 'Description')
        sh1.write(8, 1, ds.description)
        for n, p in enumerate(papers):
            sh1.write(9+n, 0, 'Paper')
            sh1.write(9+n, 1, p.citation)

        ## The edges
        el=g.get_edgelist()
        if 'name' in g.vs.attribute_names():
            n=g.vs['name']
            el=[ (n[e[0]], n[e[1]]) for e in el]
        sh2=wb.add_sheet('Edges')
        sh2.write(0, 0, 'From')
        sh2.write(0, 1, 'To')
        for n, e in enumerate(el):
            sh2.write(n+1, 0, e[0])
            sh2.write(n+1, 1, e[1])

        ## Edge attributes
        ea=g.es.attribute_names()
        for n, attr in enumerate(ea):
            sh2.write(0, n+2, attr)
            for r, v in enumerate(g.es[attr]):
                sh2.write(r+1, n+2, v)

        ## Vertex attributes
        va=g.vs.attribute_names()
        if len(va) != 0:
            sh3=wb.add_sheet('Vertices')
            for n, attr in enumerate(va):
                sh3.write(0, n, attr)
                for r, v in enumerate(g.vs[attr]):
                    sh3.write(r+1, n, v)
            
        outputfile=inputfile + excelext
        wb.save(outputfile)
        
        
    def graphml_to_pickle(self, id):
        nets=model.get_networks(id)
        basename = model.get_dataset_filename(id)
        basename = os.path.join("..", "data", id, 
                                os.path.basename(basename))
        graphmlext=model.get_format_extension('GraphML')
        outext = model.get_format_extension('Python-igraph')        
        inputfile = basename + graphmlext
        outputfile = basename + outext[:-3]

        tmp=os.path.join(tempfile.gettempdir(), "nexus")
        shutil.rmtree(tmp, ignore_errors=True)
        os.mkdir(tmp)
        os.system("unzip -d %s %s" % (tmp, inputfile))
        graphs=dict((n.sid, igraph.Graph.Read_GraphML('%s/%s.GraphML'
                                                      % (tmp, n.sid)))
                    for n in nets)
        pickle.dump(graphs, open(outputfile, "w"), protocol=-1)
        shutil.rmtree(tmp)
        gzipout(outputfile)

class Recreate(RecreateBase):    

    def GET(self, id=None):
        check_admin()
        self.r_to_graphml(id)
        self.r_to_pajek(id)
        self.graphml_to_excel(id)
        self.graphml_to_pickle(id)
        return render.recreate(id)    

class RecreateAll(RecreateBase):
    
    def GET(self, format):
        check_admin()
        web.header('Content-type','text/html')
        web.header('Transfer-Encoding','chunked')
        if format[0]!='!':
            yield render.recreateall(format)
        
        format=format[1:]
        ids=model.get_dataset_ids()
        format=format.lower()

        def to_excel(id):
            self.r_to_graphml(id)
            self.graphml_to_excel(id)

        def to_pickle(id):
            self.r_to_graphml(id)
            self.graphml_to_pickle(id)
            
        def to_r(id):
            pass

        funcs= { 'graphml': self.r_to_graphml, 
                 'pajek': self.r_to_pajek, 
                 'excel': to_excel,
                 'python-igraph': to_pickle,
                 'r-igraph': to_r }
        for id in ids:
            funcs[format](str(id.id))
            ds=list(model.get_dataset(id.id))[0]
            yield render_plain.recreate(id.id, "'" + ds.name + "'")

def update_filesize(id):
    formats=model.get_formats()
    basename=model.get_dataset_filename(id)
    for f in formats:
        ext=f.extension
        filename=os.path.join(datadir, str(id), basename + ext)
        try:
            size=os.path.getsize(filename)
            model.update_filesize(id, f.name, size)
        except:
            pass
    return True


class UpdateFilesize:    

    def GET(self, which=None):
        check_admin()
        ids=model.get_dataset_ids()
        st=[ str(id.id) + ' ' + str(update_filesize(id.id)) + '\n' 
             for id in ids ]
        return render.common('File sizes updated.\n' + str(st))

def flatten(iterables):
    return (elem for iterable in iterables for elem in iterable)

class search_clause:
    def __init__(key, field, neg):
        self.key=key
        self.field=field
        self.neg=neg

def parse_query(qstr):

    ## Tokenize search string
    state={ 'pos': 0, 'inquote': False, 'current': '', 
            'infield': False, 'tokens': [] }    
    while state['pos'] < len(qstr):
        c=qstr[state['pos']]
        if c=='"' and not state['inquote']:
            state['inquote'] = True
            state['current'] = ''
        elif c=='"' and state['inquote']:
            state['inquote'] = False
            state['tokens'].append(state['current'])
            state['current'] = ''
        elif c=='-' and state['current']=='':
            state['tokens'].append(u'-')
        elif c==' ' and not state['inquote'] and state['current'] != '':
            state['tokens'].append(state['current'])
            state['current'] = ''
        elif c==' ' and state['current'] == '':
            pass
        elif c==':' and state['current'] != '':
            state['tokens'].append(state['current'] + ':')
            state['current'] = ''            
        elif c==':' and state['currnet'] == '':
            pass
        else:
            state['current'] += c

        state['pos'] += 1
        
    if state['current'] != '':
        state['tokens'].append(state['current'])

    ## Split search expression at 'OR' keywords
    OR=[ n for n,v in enumerate(state['tokens']) if v.lower() == 'or' ]
    tokens=[]
    for s, e in izip([-1]+OR, OR+[len(state['tokens'])]):
        tokens.append(state['tokens'][s+1:e])

    return tokens

class Search:
    
    def GET(self):
        user_input=web.input(q="", order="date", format='html',
                             offset=0, limit=10)
        q=parse_query(user_input.q)
        ids=unique(reduce(lambda a,b: a+b, 
                          [model.do_search_query(t) for t in q]))

        ds, co=model.get_list_of_datasets(ids=ids, 
                                          order=user_input.order,
                                          limit=user_input.limit,
                                          offset=user_input.offset)
        tags={}
        for i in ids:
            tags[i] = list(model.get_tags(i))

        title="Nexus search results for '%s'" % user_input.q
        if user_input.format=='html':
            title="Nexus search results for '<code>%s</code>'" % user_input.q
            feed=getbase() + '/api/search?q=%s&format=atom' % user_input.q
            return render.index(ds, tags, title, feed,
                                co, int(user_input.offset)+1, 
                                int(user_input.offset)+len(ds),
                                int(user_input.limit), user_input, 
                                user_input.q)
        elif user_input.format=='xml':
            networks={}
            for i in ids:
                networks[i] = model.get_networks(i)
            web.header('Content-Type', 'text/xml')
            return render_plain.xml_index(ds, tags, len(ds), co, 
                                          int(user_input.offset),
                                          int(user_input.limit),
                                          title, networks)
        elif user_input.format=='text':
            for k, t in tags.iteritems():
                tags[k]=";".join(x.tag for x in t)
            networks={}
            for i in ids:
                networks[i] = model.get_networks(i)
            web.header('Content-Type', 'text/plain')
            return render_plain.text_index(ds, tags,
                                           len(ds), co,
                                           int(user_input.offset),
                                           int(user_input.limit),
                                           title, networks)
        elif user_input.format=='rss':
            date=datetime.today().strftime("%a, %d %b %Y %H:%M:%S +0200")
            web.header('Content-Type', 'application/rss+xml')
            return render_plain.rss_index(ds, tags, title,
                                          date, web.ctx.homedomain, '')
        elif user_input.format=='atom':
            date=datetime.today().strftime("%a, %d %b %Y %H:%M:%S +0200")
            web.header('Content-Type', 'application/atom+xml')
            return render_plain.atom_index(ds, tags, title,
                                           date, web.ctx.homedomain, '')

class Searchpage:
    
    def GET(self):
        pass

class Login:
    """Login form"""
    
    login_form = web.form.Form(
        web.form.Textbox("user", description="Username"),
        web.form.Password("passw", description="Password"),
        web.form.Button("Login")
        )

    def GET(self):
        check_safe()
        form=self.login_form()
        return render.login(form)
    
    def POST(self):
        check_safe()
        form=self.login_form()
        if not form.validates():
            # TODO
            pass

        user_input=web.input()
        authdb=sqlite3.connect("../db/users.db")
        pwdhash=hashlib.md5(user_input.passw).hexdigest()
        cur=authdb.execute('''select * from users where 
                              username=? and password=?''', 
                           (user_input.user, pwdhash))
        check=cur.fetchone()
        if check is not None:
            session.loggedin = True
            session.username = user_input.user
            session.admin = check[2] == 1
            print(session)
            redirect_to_main()
        else:
            return render.login(form)

class Logout:
    
    def GET(self):
        session.kill()
        redirect_to_main()

class Error:
    """HTTP errors"""
    
    def GET(self, code=404):
        return render.error(code)

app = web.application(urls, globals())

web.config.session_parameters['cookie_name'] = 'nexus_igraph_org'
web.config.session_parameters['cookie_domain'] = None
web.config.session_parameters['timeout'] = 20*86400,
web.config.session_parameters['ignore_expiry'] = False
web.config.session_parameters['ignore_change_ip'] = True
web.config.session_parameters['secret_key'] = '2bdbc71869ec0f268d6be1e'
web.config.session_parameters['expired_message'] = 'Session expired'

session_db = web.database(dbn="sqlite", db="../db/users.db")
store = web.session.DBStore(session_db, 'session')
session = web.session.Session(app, store, 
                              initializer={'loggedin': False, 
                                           'username': None,
                                           'admin': False })

if __name__ == '__main__':
    try:
        app.run()
    except Exception, x:
        web.header('Content-Type', 'text/plain')
        print str(x)
