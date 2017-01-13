
from config import cfg
from ut import log,jdb
import ut
from ut import Qnty,NL
from os import remove as removeFile
import re
from itertools import chain
import config
from irs import computeTitle,computeFormId,sortableFieldname

def computeFormFilename(form):
    try:
        # form may be eg ('1040','A')
        form,sched=form
        if sched is not None:
            form='%ss%s'%(form,sched)
    except Exception:
        pass
    fname='f'+form.lower().replace('-','')
    return fname
def computeFormTitle(form,parentForm=None):
    try:
        form,sched=form
        if form==parentForm[1:]:  # strip 'f' from parentForm
            form='Sched %s'%(sched,)
        elif sched is None:
            form='Form %s'%(form,)
        else:
            form='Form %s Sched %s'%(form,sched,)
    except ValueError:
        form='Form '+form
    return form
def computePageTitle(titlebase,npage,npages):
    if npages==1:
        title=titlebase
    else:
        title=titlebase+' page {}'.format(npage)
    return title
def createSvgFile(dirName,prefix,npage):
    ipage=npage-1
    infpath='{}/{}.pdf'.format(dirName,prefix)
    outfpath='{}/{}-p{}-fixedDims.svg'.format(dirName,prefix,ipage)
    outfpathFinal='{}/{}-p{}.svg'.format(dirName,prefix,npage)
    cmd='pdf2svg {} {} {}'.format(infpath,outfpath,npage)
    out,err=ut.run(cmd)
    if err:
        msg='dotaxes.py/writeEmptyHtmlPages: command [%s] returned error [%s]'%(cmd,err)
        log.error(msg)
        raise Exception(msg)
    with open(outfpath) as f:
        svg=f.read()
    # todo move draftNotice to separate file
    draftNotice='<svg width="612" height="792"><g fill="gray70" opacity="0.40"'\
        'transform="rotate(-50 420 350)"><text x="6" y="24"'\
        'transform="scale(10)">DRAFT</text><text x="-6" y="60"'\
        'transform="scale(7)">DO NOT USE</text></g></svg>'
    # insert draftNotice at end of svg file
    svg=svg.replace(' width="612pt" height="792pt"','').replace('</svg>',draftNotice+'</svg>')
    with open(outfpathFinal,'w') as f:
        f.write(svg) 
    removeFile(outfpath)
def createGifFile(dirName,prefix,npage):
    ipage=npage-1
    imgfname=prefix+'.gif'
    cmd='convert -density 144 %s/%s.pdf[%d] %s/%s'%(dirName,prefix,ipage,dirName,imgfname)
    out,err=ut.run(cmd)
    if err:
        msg='dotaxes.py/writeEmptyHtmlPages: command [%s] returned error [%s]'%(cmd,err)
        log.error(msg)
        raise Exception(msg)
    try:
        imgw,imgh=ut.readImgSize(imgfname,dirName)
    except:
        log.error('err re file '+imgfname+' in dir '+dirName)
        raise
    return imgw,imgh
def createPageImg(dirName,prefix,npage):
    imgFmt='svg'  # or 'gif'
    if imgFmt=='svg':
        imgfname='{}-p{}.svg'.format(prefix,npage)
        if not ut.exists(imgfname):
            createSvgFile(dirName,prefix,npage)
        imgw,imgh=1224,1584
    else:
        # generate page background as gif image
        imgfname='{}-p{}.gif'.format(prefix,npage)
        if not ut.exists(imgfname):
            imgw,imgh=createGifFile(dirName,prefix,npage)
    bkgdimgfname=imgfname
    return imgw,imgh,bkgdimgfname

def jsvar(s):
    return re.sub(r'[\-\[\]\.\#]','_',s)
def adjustxpos(f):
    # not f.haskey('x') means that the field inherited its xpos from a parent element rather than being positioned explicitly
    xpos=f.xpos+f.__dict__.get('dx',Qnty.fromstring('0mm'))
    return xpos
def adjustypos(f):
    if f.typ=='checkbox' and 'y' not in f.__dict__ and f.hdim>Qnty.fromstring('5mm'):
        ypos=f.ypos+(f.hdim-f.wdim)/2. # using wdim as the checkbox's actual height ob it's square
    else:
        ypos=f.ypos
    return ypos
def shorten(qnty):
    return str(qnty).replace(' millimeter','mm')
def jsterm(field,key='uniqname',display=False):
    '''
        todo still need a doctest to demo coltitle
        >>> jsterm(dict(uniqname='line3_1'))
        's.line3_1'
        >>> jsterm(dict(uniqname='f1_1'),'uniqname')
        's.f1_1'
        >>> jsterm(dict(typ='constant',val='4000'),None,True)
        '4000'
        >>> jsterm(dict(typ='constant',val='4000')) # not display, internally uses cents
        '400000'
        '''
    if field.get('typ')=='constant':
        # todo assuming integer number and thus adding '00' to convert to cents
        if display:
            return field['val']
        else:
            return '{}00'.format(field['val'])
    tmpl='s.{name}{coltitle}'
    expr=tmpl.format(
        name=jsvar(field[key]),
        coltitle=field.get('coltitle','') if key!='uniqname' else '',
        )
    if field.get('coltitle'):ut.jdb('jsterm coltitle',expr)
    return expr
def math(cfield):
    def opjoin(op,ll,termz):
        return op.join(termz)
    return ('%(lhsline)s=%(rhsexpr)s'%dict(
        lhsline=(cfield['linenum'] or '')+cfield.get('coltitle',''),
        rhsexpr=opjoin(
            cfield['op'],cfield['linenum'],
            [jsterm(depfield,'linenum',True) for depfield in cfield['deps']]),
        )).replace('s.','')
def ratio(qnty1,qnty2):
    '''
        >>> q1=Qnty.fromstring('63.5 millimeter')
        >>> q2=Qnty.fromstring('792.0 point')
        >>> str(q1/q2)
        '0.0801767676768 millimeter / point'
        >>> str(q1.to_base_units()/q2.to_base_units())
        '0.227272727273 dimensionless'
        >>> str((q1.to_base_units()/q2.to_base_units()).magnitude)
        '0.227272727273'
        >>> str(ratio(q1,q2))
        '0.227272727273'
        '''
    return (qnty1.to_base_units()/qnty2.to_base_units()).magnitude
checklift=-2
def checkbox(f,form,pageinfo,imgsize,tooltip=0):
    imgw,imgh=imgsize
    # checkboxes: <input type='checkbox' id='c1_01'><label for='c1_01' style='top:358px; left:1022px; width:31px; height:24px; text-align:center' ></label> 
    return \
    "<input type='checkbox' id='{name}' {etc}>" \
    "<label for='{name}' title='{val}'" \
    " style='top:{top:.0f}px; left:{left:.0f}px; width:{width:.0f}px; height:{height:.0f}px; text-align:center'" \
    " ></label>".format(
        #tag='textarea' if f.multiline else 'label' if f.typ=='checkbox' else 'input',
        #idattr='id' if f.typ!='checkbox' else 'for',
        name=jsvar(f.uniqname),
        val='%s %s(%s) %sx%s xy=%s,%s'%(f.name,f.linenum if f.linenum else '',f.__dict__.get('coltitle',''),shorten(f.wdim),shorten(f.hdim),shorten(f.xpos),shorten(f.ypos)) if tooltip else '',
        etc=' '.join([
            "data-bind='checked:%(name)s'"%dict(name=jsvar(f.uniqname))
            if f.name in form.upstreamFields or f.name in form.computedFields
            else ''
            ]).strip(),
        top=checklift+imgh*ratio(adjustypos(f),pageinfo.pageheight),
        left=imgw*ratio(adjustxpos(f),pageinfo.pagewidth),
        width=imgw*ratio(f.wdim,pageinfo.pagewidth),
        height=imgh*ratio(f.hdim,pageinfo.pageheight),
        )
def textbox(f,form,pageinfo,imgsize,tooltip=0):
    # textboxes: <input id='f1_01' type='text' style='top:120px; left:451px; width:182px; height:24px' >
    imgw,imgh=imgsize
    def linemath(f):
        if f.uniqname in form.computedFields:
            uniqname=f.uniqname
        elif f.unit=='cents' and f.dollarfieldname in form.computedFields:
            # for now we will not repeat the linemath in the cents field--too busy
            # NOTE this func isnt called for cents fields currently
            #uniqname=f.dollarfieldname
            return ''
        else:
            return ''
        lmath=math(form.computedFields[uniqname]).replace('line','')
        return lmath[lmath.index('='):]
    def titleValue(f):
        try:
            # moved this to sep func so that exception in mere html/title doesnt error the entire form
            return math(form.computedFields[f.uniqname]) \
                if f.uniqname in form.computedFields     \
                else '%s %s(%s) %sx%s xy=%s,%s'%(        \
                f.name,f.linenum if f.linenum else '',f.__dict__.get('coltitle',''),  \
                shorten(f.wdim),shorten(f.hdim),shorten(f.xpos),shorten(f.ypos))      \
                if tooltip \
                else ''
        except Exception:
            import traceback
            log.warn(ut.jj('caughtError:',traceback.format_exc()))
            return ''
    def dollarfieldname(f):
        return form.fieldsByName[f.uniqname].get('dollarfieldname')
    return \
    "<{tag} id='{name}' type='{typ}' {etc} title='{val}'" \
    " style='top:{top:.0f}px; left:{left:.0f}px; width:{width:.0f}px; height:{height:.0f}px'" \
    " >{endtag}".format(
        tag='textarea' if f.multiline else 'input',
        name=jsvar(f.uniqname),
        #val=f.name[-(int(f.maxchars) if f.maxchars is not None else 0):]+' %sx%s'%(f.wdim,f.hdim) if cfg.debug else '',
        val=titleValue(f),
        typ=f.typ,
        etc=' '.join([
            'maxlength='+f.maxchars if f.maxchars else '',
            "class='dd'" if f.unit=='dollars' else '',
            '%s'%('readonly placeholder="%s"'%(linemath(f)) if f.uniqname in form.computedFields and f.deps else ''),
            "data-bind='value:%(name)s'"%dict(
                name=jsvar(f.uniqname))
                if f.uniqname in form.upstreamFields or f.uniqname in form.computedFields or \
                  dollarfieldname(f) in form.upstreamFields  \
                  or dollarfieldname(f) in form.computedFields
                else ''
            ]).strip(),
        top=imgh*ratio(adjustypos(f),pageinfo.pageheight),
        left=imgw*ratio(adjustxpos(f),pageinfo.pagewidth),
        width=imgw*ratio(f.wdim,pageinfo.pagewidth),
        height=imgh*ratio(f.hdim,pageinfo.pageheight),
        endtag='</textarea>' if f.multiline else '</label>' if f.typ=='checkbox' else '',
        )

def computeSteps(cfield):
    # generate js code for arithmetic
    # f1040/line37: var result=s.line22()-s.line36(); return result;
    # f1040/line42: var result=400000*s.line6d_5(); if(s.line38()>15495000)result="-0-"; return result;
    jdb('>computeSteps',cfield,cfield.get('deps'),cfield['op'],cfield.get('math'))
    steps=[]
    if cfield.get('deps'):
        steps.append(
            'var result=%s;'%(cfield['op'].join(
                jsterm(dep,'uniqlinenum')+('()' if dep.get('typ')!='constant' else '')
                for dep in cfield['deps'])))
    if cfield['math'].get('zcond'):
        def termify(linenum):
            if linenum.startswith('line'):
                return 's.%s()'%(linenum,)
            else:
                return linenum+'00'  # eg constant
        op,left,right=cfield['math'].get('zcond')
        steps.append(('if(%s)result="-0-";'%(op.join((termify(left),termify(right))),)))
        def uniqifyDep(sideval,whichside,deps):
            '''
            toward doctests
            DEBUG:f1040:>uniqifyDep line38 left ['line6d_5']     # for f1040/line42
            DEBUG:f1040:<uniqifyDep line38
            '''
            ut.jdb('>uniqifyDep',sideval,whichside,deps)
            sideval0=sideval
            # 'sideval' as in lhs value or rhs value
            # this prevents js "result=line4-line5_3; if(line5>line4)result=0" in which line5 is not defined
            if sideval not in uniqlinenums:
                startswithz=[uniqlinenum for uniqlinenum in uniqlinenums if uniqlinenum.startswith(sideval)]
                if len(startswithz)==1:
                    sideval=startswithz[0]
                elif not startswithz:
                    #raise Exception('computeSteps: zcond %s [%s] matches w/ none of deps [%s]'%(whichside,sideval,uniqlinenums))
                    pass  # can be ok eg 1040/line42 uses line6d but checks line38
                    # todo check against the full list of available variables, not just the variables on current line of form
                else:
                    # eg cannot yet generate math for f8880/line5 [implicitly for cols a and b]
                    log.error('computeSteps: zcond term %s [%s] matches w/ more than one of deps [%s] in field [%s]',
                        whichside,sideval,uniqlinenums,cfield['speak'])
            if sideval!=sideval0:
                ut.jdb('<uniqifyDep',sideval)
            return sideval
        uniqlinenums=[d['uniqlinenum'] for d in cfield['deps'] if 'uniqlinenum' in d]
        if left.startswith('line'):
            left=uniqifyDep(left,'left',uniqlinenums)
        if right.startswith('line'):
            right=uniqifyDep(right,'right',uniqlinenums)
    steps.append('return result;')
    result=' '.join(steps)
    jdb('<computeSteps',result)
    return result

def pagelinkhtml(prefix,npage,npages,imgw):
    # generate the next and prev page links
    linkwidthprop=float(24)/imgw  # todo dont hardcode width of 24x24.png icon
    #marginw=.05
    def pagelinktmpl(nnpage,npages,whichway):
        jdb('>pagelinktmpl',nnpage,npages,whichway)
        if 1<=nnpage<=npages:
            result="<a id='{whichway}pagelink' href='{prefix}-p{npage}.html' title='page {npage}' style='top:{top:.0f}px; left:{left:.0f}px;'>" \
                "<img src='static/img/arrow_%s_32px.png'></a>"%(whichway)
        else:
            result="<img src='static/img/arrow_%s_gray_32px.png' style='top:{top:.0f}px; left:{left:.0f}px;'>"%(whichway)
        jdb('<pagelinktmpl',result)
        return result
    return NL.encode('utf8').join(
        pagelinktmpl(nnpage,npages,whichway).format(
            prefix=prefix,
            npage=nnpage,
            whichway=whichway,
            top=0,
            left=imgw*(1-nicon*linkwidthprop),
        # count back from nicons to 1 because nicon is subtracted from pageWidth
        ) for nicon,nnpage,whichway in ((2,npage-1,'prev'),(1,npage+1,'next'))
        )

def getSigns(field,unit=None):
    jdb('>getSigns',field,unit,field['deps'],[d.get('sign',' ') for d in field['deps']])
    requiredarg=(unit is not None)
    signs=''.join(dep.get('sign',' ')
        for dep in field['deps']
            if (unit is None or unit==dep['unit']))
    if '-' in signs:
        result=',"'+signs+'"'
    elif requiredarg:
        result=',""'
    else:
        result=''
    if result:
        jdb('<getSigns',result)
    return result

def writeEmptyHtmlPages(form):
    # generate html form fields overlaid on image of the form
    if 'h' not in cfg.steps:
        return
    formName=form.formName
    dirName=cfg.dirName
    prefix=form.prefix
    pageinfo=form.pageinfo
    formrefs=form.refs
    npages=len(pageinfo)
    template=ut.Resource('opentaxforms','template/form.html').content()
    emptyHtml=template.replace('{','{{').replace('}','}}').replace('[=[','{').replace(']=]','}')
    titlebase=computeTitle(prefix)
    for npage in range(1,1+npages):
        title=computePageTitle(titlebase,npage,npages)
        imgw,imgh,bkgdimgfname=createPageImg(dirName,prefix,npage)
        # inputboxes can be
        #   checkboxes: <input type='checkbox' id='c1_01' '><label for='c1_01' style='top:358px; ...; text-align:center' ></label> 
        #   or textboxes: <input id='f1_01' type='text' style='top:120px; left:451px; width:182px; height:24px' >
        inputboxes='\n'.join(
            checkbox(f,form,pageinfo[npage],(imgw,imgh),cfg.verbose) \
            if f.typ=='checkbox' \
            else textbox(f,form,pageinfo[npage],(imgw,imgh),cfg.verbose)
            for f in form.bfields if f.npage==npage and not f.isReadonly)
        # generate js code for automath
        # math dependencies [examples from f1040]
        # todo accommodate multiple taxpayers or multiple w2 forms
        dbid='opentaxforms_%s'%(cfg.formyear)
        formid=computeFormId(formName)   # eg 1040 or 1040sb??
        # create lists of js variables to process [see form.html]
        # inputdepsUnitless is unitless (eg nonmonetary) boxes eg counting number of boxes checked
        inputdepsUnitless=["{name}".format(
            name=jsvar(name))
            for name in form.upstreamFields
            if form.fieldsByName[name]['unit'] is None and form.fieldsByName[name]['npage']==npage]
        # inputdepsDc is dollar n cents pairs
        # centfield handled seply cuz 1040a/40 has dollar field w/ no centfield partner
        inputdepsDc=["{dname}{centfield}".format(
            dname=jsvar(name),
            #debug=log.debug(jj(877,f['uniqname'],f['deps'])),  # reminder of an unusual way to debug
            centfield=" {cname}".format(
                cname=jsvar(form.fieldsByName[name]['centfield']['uniqname'])) if 'centfield' in form.fieldsByName[name] else '')
            for name in form.upstreamFields
            if form.fieldsByName[name]['unit']=='dollars' and form.fieldsByName[name]['npage']==npage]
        computedz=' '.join('{field}{centfield}'.format(
            field=jsvar(cfield['uniqname']),
            centfield=(' '+jsvar(cfield['centfield']['uniqname'])) if 'centfield' in cfield else ''
            ) for cfield in form.computedFields.values() if cfield['npage']==npage)
        # off-page deps of computedz [wh could be computedz on their own page and thus removed above [seek 'delays' in dotaxes.computeMath]]
        inputdepsOffpage=['{field}{centfield}'.format(
            field=jsvar(dep['uniqname']),
            centfield=(' '+dep['centfield']['uniqname']) if 'centfield' in dep else ''
            ) for cfield in form.computedFields.values() if cfield['npage']==npage for dep in cfield['deps'] if dep['npage']!=npage]
        obsvblz=' '.join(chain(inputdepsUnitless,inputdepsDc,inputdepsOffpage))   # eg 'c1_04 c1_05 f1_31 f1_32 f1_33'
        readonlyz=' '.join(inputdepsOffpage)
        nonobsvblz=' '.join(jsvar(f.uniqname)
            for f in form.bfields
                if f.uniqname not in form.upstreamFields
                and f.uniqname not in form.computedFields  # eg 'f1_24 f1_27'
                and f.uniqname not in obsvblz         # else some obsvbls [centfields?] get into nonobsvblz
                and form.fieldsByName[f.uniqname]['npage']==npage)
        obsvblz=' '.join(sorted(obsvblz.split(),key=sortableFieldname))
        readonlyz=' '.join(sorted(readonlyz.split(),key=sortableFieldname))
        nonobsvblz=' '.join(sorted(nonobsvblz.split(),key=sortableFieldname))
        # inputdepsSingle are computed from individual [ie not paired] unitless [not dollars or cents] boxes
        # such as counting chkboxes
        # example output:
        #s.f1_30=koc(pp("+",[s.c1_04,s.c1_05]));//line6d=line6a+line6b
        inputdepsSingle=[
            's.%(lhsname)s=koc(pp("%(op)s",[%(terms)s]%(signs)s));%(math)s'%dict(
                lhsname=jsvar(cfield['uniqname']),
                op=cfield['op'],
                terms=','.join(jsterm(depfield) for depfield in cfield['deps']),
                signs=getSigns(cfield),
                math='//'+math(cfield) if cfg.debug else '',
                )
            for cfield in form.computedFields.values()
            if cfield['unit'] is None and cfield['npage']==npage #and cfield['op']!='?'
            ]
        alreadyDefined=set()
        # inputdepsPair are computed from dollars and cents pairs of boxes
        # centfield is optional cuz eg f1116 has just single fields for monetary values
        # example output:
        #//line41=line38-line40
        #s.line40=koc(ll(s.f2_04,s.f2_05,"line40"));
        #s.line41=koc(function(){var result=s.line38()-s.line40(); return result;});
        #s.f2_06=koc(zz(dd(s.line41)));
        #s.f2_07=koc(zz(cc(s.line41)));
        inputdepsPair=[
            '%(math)s'
            '%(deps)s\n'
            's.%(line)s=koc(function(){%(steps)s});\n'
            's.%(dname)s=koc(zz(dd(s.%(line)s)));\n'
            '%(centfieldOptional)s'%dict(
                line=cfield['uniqlinenum'],
                deps=' '.join('s.%s=koc(%s(%s,%s%s));'%(
                    depfield['uniqlinenum'],
                    'll' if depfield['unit']=='dollars' else 'nn',
                    jsterm(depfield),
                    jsterm(depfield['centfield']) if 'centfield' in depfield else 'null',
                    ',"%s"'%(depfield['uniqlinenum'],))
                    # unit may be dollars or none [as in 1040/line42 = line6d x $4000] but not cents
                    for depfield in cfield['deps']
                    if depfield['unit']!='cents' and depfield.get('typ')!='constant' and \
                    depfield['uniqlinenum'] not in alreadyDefined),
                steps=computeSteps(cfield),
                dname=jsvar(cfield['uniqname']),
                centfieldOptional='s.%(cname)s=koc(zz(cc(s.%(line)s)));'%dict(
                    cname=jsvar(cfield['centfield']['uniqname']),
                    line=cfield['uniqlinenum']) if 'centfield' in cfield else '',
                math='//'+math(cfield)+NL if cfg.debug else '',
                storeDeps=[alreadyDefined.add(depfield['uniqlinenum'])
                    for depfield in cfield['deps'] if depfield['unit']!='cents' and \
                        depfield.get('typ')!='constant'],
                storeComputdz=alreadyDefined.add(cfield['uniqlinenum']),
                )
            for cfield in sorted(form.computedFields.values(),key=lambda cf:cf['ypos'])
            if cfield['unit']=='dollars' and cfield['npage']==npage
            ]
        inputdeps='\n'.join(chain(inputdepsSingle,inputdepsPair))
        pagelinks=pagelinkhtml(prefix,npage,npages,imgw)
        formlinks='\n'.encode('utf8').join(
            "<a id='{name}' href='{fname}-p1.html' title='{tip}' " \
            "style='font-color:orange; top:{top:.0f}px; left:{left:.0f}px; width:{width:.0f}px; height:{height:.0f}px; '></a>".format(
            # \n\t<!--{comment:.0f}-->                  # for embedding comment in the html output
            #comment=bbox.y0.to_base_units().magnitude, # for filling said comment
            name=data['draw']['name'],
            fname=computeFormFilename(form),
            tip=computeFormTitle(form,formName)+('[match:%s]'%(data['match']) if cfg.debug else ''),
            top=imgh*(1-(bbox.y1/pageinfo[npage].pageheight).magnitude),
            left=imgw*(bbox.x0/pageinfo[npage].pagewidth).magnitude,
            width=imgw*((bbox.x1-bbox.x0)/pageinfo[npage].pagewidth).magnitude,
            height=imgh*((bbox.y1-bbox.y0)/pageinfo[npage].pageheight).magnitude,
            ).encode('utf8')
            for form,data in formrefs.items()
            if data['draw']['npage']==npage and 'bboxz' in data
            for bbox in data['bboxz'])
        open(dirName+'/%s-p%d.html'%(prefix,npage),'w').write(emptyHtml.format(
            title=       title,
            bkgdimgfname=bkgdimgfname,
            dbid=        dbid,
            formid=      formid,
            pagelinks=   pagelinks,  
            inputboxes=  inputboxes,
            formlinks=   formlinks,
            readonlyz=   readonlyz,
            nonobsvblz=  nonobsvblz,
            obsvblz=     obsvblz,
            inputdeps=   inputdeps,
            computedz=   computedz,
            ))

if __name__=="__main__":
    config.setup()
    if cfg.doctests:
        import doctest; doctest.testmod(verbose=cfg.verbose)

