#!/usr/bin/env python

import time
import base64
import re
from saml2 import samlp, saml, VERSION, sigver, NAME_FORMAT_URI
from saml2.time_util import instant

try:
    from hashlib import md5
except ImportError:
    from md5 import md5
import zlib

class VersionMismatch(Exception):
    pass
    
class UnknownPrincipal(Exception):
    pass
    
class UnsupportedBinding(Exception):
    pass

class OtherError(Exception):
    pass

class MissingValue(Exception):
    pass
    
EXCEPTION2STATUS = {
    VersionMismatch: samlp.STATUS_VERSION_MISMATCH,
    UnknownPrincipal: samlp.STATUS_UNKNOWN_PRINCIPAL,
    UnsupportedBinding: samlp.STATUS_UNSUPPORTED_BINDING,
    OtherError: samlp.STATUS_UNKNOWN_PRINCIPAL,
    MissingValue: samlp.STATUS_REQUEST_UNSUPPORTED,
}

GENERIC_DOMAINS = "aero", "asia", "biz", "cat", "com", "coop", \
        "edu", "gov", "info", "int", "jobs", "mil", "mobi", "museum", \
        "name", "net", "org", "pro", "tel", "travel"

def valid_email(emailaddress, domains = GENERIC_DOMAINS):
    """Checks for a syntactically valid email address."""

    # Email address must be at least 6 characters in total.
    # Assuming noone may have addresses of the type a@com
    if len(emailaddress) < 6:
        return False # Address too short.

    # Split up email address into parts.
    try:
        localpart, domainname = emailaddress.rsplit('@', 1)
        host, toplevel = domainname.rsplit('.', 1)
    except ValueError:
        return False # Address does not have enough parts.

    # Check for Country code or Generic Domain.
    if len(toplevel) != 2 and toplevel not in domains:
        return False # Not a domain name.

    for i in '-_.%+.':
        localpart = localpart.replace(i, "")
    for i in '-_.':
        host = host.replace(i, "")

    if localpart.isalnum() and host.isalnum():
        return True # Email address is fine.
    else:
        return False # Email address has funny characters.
            
def decode_base64_and_inflate( string ):
    """ base64 decodes and then inflates according to RFC1951 
    
    :param string: a deflated and encoded string
    :return: the string after decoding and inflating
    """

    return zlib.decompress( base64.b64decode( string ) , -15)

def deflate_and_base64_encode( string_val ):
    """
    Deflates and the base64 encodes a string
    
    :param string_val: The string to deflate and encode
    :return: The deflated and encoded string
    """
    return base64.b64encode( zlib.compress( string_val )[2:-4] )
    
def sid(seed=""):
    """The hash of the server time + seed makes an unique SID for each session.
    
    :param seed: A seed string
    :return: The hex version of the digest
    """
    ident = md5()
    ident.update(repr(time.time()))
    if seed:
        ident.update(seed)
    return ident.hexdigest()

def make_vals(val, klass, klass_inst=None, prop=None, part=False,
                base64encode=False):
    """
    Creates a class instance with a specified value, the specified
    class instance are a value on a property in a defined class instance.
    
    :param val: The value
    :param klass: The value class
    :param klass_inst: The class instance which has a property on which 
        what this function returns is a value.
    :param prop: The property which the value should be assigned to.
    :param part: If the value is one of a possible list of values it should be
        handled slightly different compared to if it isn't.
    :return: Value class instance
    """
    cinst = None
    #print "_make_val: %s %s (%s) [%s]" % (prop,val,klass,part)
    if isinstance(val, bool):
        cinst = klass(text="%s" % val)
    elif isinstance(val, int):
        cinst = klass(text="%d" % val)
    elif isinstance(val, basestring):
        cinst = klass(text=val)
    elif val == None:
        cinst = klass()
    elif isinstance(val, dict):
        cinst = make_instance(klass, val, base64encode=base64encode)
    elif not part:
        cis = [make_vals(sval, klass, klass_inst, prop, True, 
                        base64encode) for sval in val]
        setattr(klass_inst, prop, cis)
    else:
        raise ValueError("strange instance type: %s on %s" % (type(val), val))
        
    if part:
        return cinst
    else:        
        if cinst:            
            cis = [cinst]
            setattr(klass_inst, prop, cis)
    
def make_instance(klass, spec, base64encode=False):
    """
    Constructs a class instance containing the specified information
    
    :param klass: The class
    :param spec: Information to be placed in the instance (a dictionary)
    :return: The instance
    """
    #print "----- %s -----" % klass
    #print "..... %s ....." % spec
    klass_inst = klass()
    for prop in klass.c_attributes.values():
        #print "# %s" % (prop)
        if prop in spec:
            if isinstance(spec[prop], bool):
                setattr(klass_inst, prop,"%s" % spec[prop])
            elif isinstance(spec[prop], int):
                setattr(klass_inst, prop, "%d" % spec[prop])
            else:
                setattr(klass_inst, prop, spec[prop])

    if "text" in spec:
        val = spec["text"]
        print "<<", klass
        if klass == saml.AttributeValue:
            print ">> AVA"
            if base64encode:
                import base64
                val = base64.encodestring(val)
                setattr(klass_inst, "type", saml.NS_SOAP_ENC + "base64")
            else:
                if isinstance(val, basestring):
                    print "basestring"
                    setattr(klass_inst, "type", "xs:string")
                    print klass_inst.__dict__
                elif isinstance(val, bool):
                    print "boolean", val
                    if val:
                        val = "true"
                    else:
                        val = "false"
                    setattr(klass_inst, "type", "xs:boolean")
                elif isinstance(val, int):
                    val = str(val)
                    setattr(klass_inst, "type", "xs:integer")
                elif isinstance(val, float):
                    val = str(val)
                    setattr(klass_inst, "type", "xs:float")
            
        setattr(klass_inst, "text", val)
        
    for prop, klass in klass.c_children.values():
        #print "## %s, %s" % (prop, klass)
        if prop in spec:
            #print "%s" % spec[prop]
            if isinstance(klass, list): # means there can be a list of values
                make_vals(spec[prop], klass[0], klass_inst, prop,
                            base64encode=base64encode)
            else:
                cis = make_vals(spec[prop], klass, klass_inst, prop, True,
                            base64encode)
                setattr(klass_inst, prop, cis)
    #+print ">>> %s <<<" % klass_inst
    return klass_inst

def parse_attribute_map(filenames):
    """
    Expects a file with each line being composed of the oid for the attribute
    exactly one space, a user friendly name of the attribute and then
    the type specification of the name.
    
    :param filename: List of filenames on mapfiles.
    :return: A 2-tuple, one dictionary with the oid as keys and the friendly 
        names as values, the other one the other way around.
    """
    forward = {}
    backward = {}
    for filename in filenames:
        for line in open(filename).readlines():
            (name, friendly_name, name_format) = line.strip().split()
            forward[(name, name_format)] = friendly_name
            backward[friendly_name] = (name, name_format)
        
    return (forward, backward)

def filter_attribute_value_assertions(ava, attribute_restrictions=None):
    """ Will weed out attribute values and values according to the 
    rules defined in the attribute restrictions. If filtering results in 
    an attribute without values, then the attribute is removed from the
    assertion.
    
    :param ava: The incoming attribute value assertion
    :param attribute_restrictions: The rules that govern which attributes
        and values that are allowed.
    :return: A attribute value assertion
    """
    if not attribute_restrictions:
        return ava
        
    resava = {}
    for attr, vals in ava.items():
        if attr in attribute_restrictions:
            if attribute_restrictions[attr] == None:
                resava[attr] = vals
            else:    
                rvals = []
                for restr in attribute_restrictions[attr]:
                    for val in vals:
                        if restr.match(val):
                            rvals.append(val)
                
                if rvals:
                    resava[attr] = list(set(rvals))
    return resava
    
def identity_attribute(form, attribute, forward_map=None):
    if form == "friendly":
        if attribute.friendly_name:
            return attribute.friendly_name
        elif forward_map:
            try:
                return forward_map[(attribute.name, attribute.name_format)]
            except KeyError:
                return attribute.name
    # default is name
    return attribute.name

def _filter_values(vals, required=None, optional=None):
    """ Removes values from *val* that does not appear in *attributes*.
    
    :param val: The values that are to be filtered
    :param required: The required values
    :param optional: The optional values
    :return: The set of values after filtering
    """

    if not required and not optional:
        return vals
        
    valr = []
    valo = []
    if required:
        rvals = [v.text for v in required]
    else:
        rvals = []
    if optional:
        ovals = [v.text for v in optional]
    else:
        ovals = []
    for val in vals:
        if val in rvals:
            valr.append(val)
        elif val in ovals:
            valo.append(val)

    valo.extend(valr)
    if rvals:
        if len(rvals) == len(valr):
            return valo
        else:
            raise MissingValue("Required attribute value missing")
    else:
        return valo
    
def _combine(required=None, optional=None):
    res = {}
    if not required:
        required = []
    if not optional:
        optional = []
    for attr in required:
        part = None
        for oat in optional:
            if attr.name == oat.name:
                part = (attr.attribute_value, oat.attribute_value)
                break
        if part:
            res[(attr.name, attr.friendly_name)] = part
        else:
            res[(attr.name, attr.friendly_name)] = (attr.attribute_value, [])

    for oat in optional:
        tag = (oat.name, oat.friendly_name)
        if tag not in res:
            res[tag] = ([], oat.attribute_value)
            
    return res
    
def filter_on_attributes(ava, required=None, optional=None):
    """ Filter
    :param required: list of RequestedAttribute instances
    """
    res = {}
    comb = _combine(required, optional)
    for attr, vals in comb.items():
        if attr[0] in ava:
            res[attr[0]] = _filter_values(ava[attr[0]], vals[0], vals[1])
        elif attr[1] in ava:
            res[attr[1]] = _filter_values(ava[attr[1]], vals[0], vals[1])
        else:
            raise MissingValue("Required attribute missing")
    
    return res
    

#----------------------------------------------------------------------------

def _properties(klass):
    props = [val[0] for _, val in klass.c_children.items()]
    props.extend(klass.c_attributes.values())
    return props
    
def args2dict(text=None, **kwargs):
    spec = kwargs.copy()
    if text != None:
        spec["text"] = text
    return spec

def _klassdict(klass, text=None, **kwargs):
    """ Does not remove attributes with no values """
    spec = {}
    if text:
        spec["text"] = text
    props = _properties(klass)
    #print props
    for key, val in kwargs.items():
        #print "?",key
        if key in props:
            spec[key] = val
    return spec
    
def status_from_exception_factory(exception):
    msg = exception.args[0]
    return args2dict(
        status_message=msg,
        status_code=args2dict(
            value=samlp.STATUS_RESPONDER,
            status_code=args2dict(value=EXCEPTION2STATUS[exception.__class__])
            ),
    )
        
def success_status_factory():
    return args2dict(status_code=args2dict(value=samlp.STATUS_SUCCESS))
                                
def assertion_factory(text="", **kwargs):
    kwargs.update({
        "version": VERSION,
        "id" : sid(),
        "issue_instant" : instant(),
    })
    return args2dict(text, **kwargs)        
    
def response_factory(signature=False, encrypt=False, **kwargs):
    kwargs.update({
        "id" : sid(),
        "version": VERSION,
        "issue_instant" : instant(),
    })
    if signature:
        kwargs["signature"] = sigver.pre_signature_part(kwargs["id"])
    if encrypt:
        pass
    return args2dict(**kwargs)        

def _attrval(val):
    if isinstance(val, list) or isinstance(val,set):
        attrval = [args2dict(v) for v in val]
    elif val == None:
        attrval = None
    else:
        attrval = [args2dict(val)]

    return attrval

# --- attribute profiles -----

# xmlns:xs="http://www.w3.org/2001/XMLSchema"
# xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"

def _basic_val(val):
    if isinstance(val, basestring):
        attrval = [args2dict(val, type="xs:string")]
    elif isinstance(val, int):
        attrval = [args2dict(val, type="xs:integer")]
    elif isinstance(val, list):
        attrval = [_basic_val(v) for v in val]
    elif val == None:
        attrval = None
    else:
        raise OtherError("strange value type on: %s" % val)

    return attrval

def basic_attribute(attribute, value):
    """<saml:Attribute NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:basic" Name="cn">
                <saml:AttributeValue xsi:type="xs:string">Andreas Solberg</saml:AttributeValue>
            </saml:Attribute>
    """
    attr = {}
    attr["name_format"] = NAME_FORMAT_BASIC
    attr["name"] = attribute
    
    return attr
    
def ava_to_attributes(ava, bmap=None):
    attrs = []
    
    for friendly_name, val in ava.items():
        dic = {}
        attrval = _attrval(val)
        if attrval:
            dic["attribute_value"] = attrval
        
        dic["friendly_name"] = friendly_name
        if bmap:
            try:
                (dic["name"], dic["name_format"]) = bmap[friendly_name]
            except KeyError:
                pass
        attrs.append(args2dict(**dic))
    return attrs

def do_ava_statement(identity, bmap):
    """
    :param identity: A dictionary with fiendly names as keys
    :return:
    """
    return args2dict(attribute=ava_to_attributes(identity, bmap))

def do_attributes(identity):
    attrs = []
    if not identity:
        return attrs
    for key, val in identity.items():
        dic = {}

        attrval = _attrval(val)
        if attrval:
            dic["attribute_value"] = attrval

        if isinstance(key, basestring):
            dic["name"] = key
        elif isinstance(key, tuple): # 3-tuple
            try:
                (name, nformat, friendly) = key
            except ValueError:
                (name, nformat) = key
                friendly = ""
            if name:
                dic["name"] = name
            if format:
                dic["name_format"] = nformat
            if friendly:
                dic["friendly_name"] = friendly
        attrs.append(args2dict(**dic))
    return attrs
    
def do_attribute_statement(identity):
    """
    :param identity: A dictionary with fiendly names as keys
    :return:
    """
    return args2dict(attribute=do_attributes(identity))

