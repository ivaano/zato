# -*- coding: utf-8 -*-

"""
Copyright (C) 2011 Dariusz Suchojad <dsuch at gefira.pl>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

# stdlib
import logging
from json import dumps
from traceback import format_exc

# Django
from django.http import HttpResponse, HttpResponseServerError
from django.shortcuts import render_to_response

# lxml
from lxml import etree
from lxml.objectify import Element

# Validate
from validate import is_boolean

# Zato
from zato.admin.web import invoke_admin_service
from zato.admin.web.forms import ChooseClusterForm
from zato.admin.web.forms.channel.soap import DefinitionForm
from zato.admin.web.views import change_password as _change_password, meth_allowed
from zato.common import zato_namespace, zato_path, ZatoException, ZATO_NOT_GIVEN
from zato.common.odb.model import Cluster, ChannelURLDefinition
from zato.common.util import pprint, TRACE1

logger = logging.getLogger(__name__)

def _get_edit_create_message(params, prefix=''):
    """ Creates a base document which can be used by both 'edit' and 'create' actions.
    """
    zato_message = Element('{%s}zato_message' % zato_namespace)
    zato_message.data = Element('data')
    zato_message.data.id = params.get('id')
    zato_message.data.cluster_id = params['cluster_id']
    zato_message.data.url_pattern = params[prefix + 'url_pattern']

    return zato_message

@meth_allowed('GET')
def index(req):

    zato_clusters = req.odb.query(Cluster).order_by('name').all()
    choose_cluster_form = ChooseClusterForm(zato_clusters, req.GET)
    cluster_id = req.GET.get('cluster')
    items = []
    
    create_form = DefinitionForm()
    edit_form = DefinitionForm(prefix='edit')
    
    from zato.common.odb.model import(ChannelURLDefinition, ChannelURLSecurity,
            HTTPBasicAuth, SecurityDefinition, TechnicalAccount, WSSDefinition)
    
    definitions = req.odb.query(ChannelURLDefinition.id,
        ChannelURLDefinition.url_pattern,
        SecurityDefinition.security_def_type.label('sec_def_type'),
        HTTPBasicAuth.id.label('basic_auth_id'),
        HTTPBasicAuth.name.label('basic_auth_name'),
        TechnicalAccount.id.label('tech_acc_id'),
        TechnicalAccount.name.label('tech_acc_name'),
        WSSDefinition.id.label('wss_id'),
        WSSDefinition.name.label('wss_name'),
        ).\
            outerjoin(ChannelURLSecurity, 
                      ChannelURLSecurity.channel_url_def_id==ChannelURLDefinition.id).\
            outerjoin(SecurityDefinition, 
                      SecurityDefinition.id==ChannelURLSecurity.security_def_id).\
            outerjoin(HTTPBasicAuth, 
                      HTTPBasicAuth.security_def_id==SecurityDefinition.id).\
            outerjoin(TechnicalAccount, 
                      TechnicalAccount.security_def_id==SecurityDefinition.id).\
            outerjoin(WSSDefinition, 
                      WSSDefinition.security_def_id==SecurityDefinition.id).\
            order_by(ChannelURLDefinition.url_pattern)
    
    print(definitions)
    print(definitions.all())

    if cluster_id and req.method == 'GET':
        cluster = req.odb.query(Cluster).filter_by(id=cluster_id).first()

        zato_message = Element('{%s}zato_message' % zato_namespace)
        zato_message.data = Element('data')
        zato_message.data.cluster_id = cluster_id

        _ignored, zato_message, soap_response  = invoke_admin_service(cluster,
                'zato:channel.soap.get-list', zato_message)

        if zato_path('data.definition_list.definition').get_from(zato_message) is not None:
            for definition_elem in zato_message.data.definition_list.definition:

                id = definition_elem.id.text
                url_pattern = definition_elem.url_pattern.text
                is_internal = is_boolean(definition_elem.is_internal.text)

                items.append(ChannelURLDefinition(id, url_pattern, 
                                'soap', is_internal))

    return_data = {'zato_clusters':zato_clusters,
        'cluster_id':cluster_id,
        'choose_cluster_form':choose_cluster_form,
        'items':items,
        'create_form': create_form,
        'edit_form': edit_form,
        }

    # TODO: Should really be done by a decorator.
    if logger.isEnabledFor(TRACE1):
        logger.log(TRACE1, 'Returning render_to_response [%s]' % return_data)

    return render_to_response('zato/channel/soap.html', return_data)

@meth_allowed('POST')
def edit(req):
    """ Updates the HTTP Basic Auth definition's parameters (everything except
    for the password).
    """
    try:
        cluster_id = req.POST.get('cluster_id')
        cluster = req.odb.query(Cluster).filter_by(id=cluster_id).first()
        zato_message = _get_edit_create_message(req.POST, prefix='edit-')

        _, zato_message, soap_response = invoke_admin_service(cluster,
                                    'zato:security.basic-auth.edit', zato_message)
    except Exception, e:
        msg = "Could not update the HTTP Basic Auth definition, e=[{e}]".format(e=format_exc(e))
        logger.error(msg)
        return HttpResponseServerError(msg)
    else:
        return HttpResponse()

@meth_allowed('POST')
def create(req):
    try:
        cluster_id = req.POST.get('cluster_id')
        cluster = req.odb.query(Cluster).filter_by(id=cluster_id).first()

        zato_message = _get_edit_create_message(req.POST)

        _, zato_message, soap_response = invoke_admin_service(cluster,
                            'zato:security.basic-auth.create', zato_message)
    except Exception, e:
        msg = "Could not create an HTTP Basic Auth definition, e=[{e}]".format(e=format_exc(e))
        logger.error(msg)
        return HttpResponseServerError(msg)
    else:
        return_data = {'pk': zato_message.data.basic_auth.id.text}
        return HttpResponse(dumps(return_data), mimetype='application/javascript')

@meth_allowed('POST')
def delete(req, id, cluster_id):
    
    cluster = req.odb.query(Cluster).filter_by(id=cluster_id).first()
    
    try:
        zato_message = Element('{%s}zato_message' % zato_namespace)
        zato_message.data = Element('data')
        zato_message.data.id = id
        
        _, zato_message, soap_response = invoke_admin_service(cluster,
                        'zato:security.basic-auth.delete', zato_message)
    
    except Exception, e:
        msg = "Could not delete the HTTP Basic Auth definition, e=[{e}]".format(e=format_exc(e))
        logger.error(msg)
        return HttpResponseServerError(msg)
    else:
        return HttpResponse()
    