#
# Copyright 2013 - Tom Alessi
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Views for the SSD Project that pertain to managing incidents

"""


import datetime
import pytz
import re
from django.conf import settings
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.http import HttpResponseRedirect
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.utils import timezone as jtz
from ssd.main.models import Event
from ssd.main.models import Event_Description
from ssd.main.models import Event_Service
from ssd.main.models import Event_Status
from ssd.main.models import Event_Time
from ssd.main.models import Event_User
from ssd.main.models import Event_Update
from ssd.main.models import Event_Email
from ssd.main.models import Event_Impact
from ssd.main.models import Event_Coordinator
from ssd.main.models import Service
from ssd.main.models import Email
from ssd.main.forms import AddIncidentForm
from ssd.main.forms import DeleteEventForm
from ssd.main.forms import UpdateIncidentForm
from ssd.main.forms import DetailForm
from ssd.main import notify
from ssd.main import config_value
from ssd.main.views.system import system_message


@login_required
@staff_member_required
def incident(request):
    """Create Incident Page

    Create a new incident

    """

    # Instantiate the configuration value getter
    cv = config_value.config_value()

    # Obtain the timezone (or set to the default DJango server timezone)
    if request.COOKIES.get('timezone') == None:
        set_timezone = settings.TIME_ZONE
    else:
        set_timezone = request.COOKIES.get('timezone')
    
    # If this is a POST, then validate the form and save the data
    # Some validation must take place manually
    if request.method == 'POST':

        # If this is a form submit that fails, we want to reset whatever services were selected
        # by the user.  Templates do not allow access to Arrays stored in QueryDict objects so we have
        # to determine the list and send back to the template on failed form submits
        affected_svcs = request.POST.getlist('service')

        # Check the form elements
        form = AddIncidentForm(request.POST)

        if form.is_valid():
            # Obtain the cleaned data
            s_date = form.cleaned_data['s_date']
            s_time = form.cleaned_data['s_time']
            e_date = form.cleaned_data['e_date']
            e_time = form.cleaned_data['e_time']
            detail = form.cleaned_data['detail']
            broadcast = form.cleaned_data['broadcast']
            email_id = form.cleaned_data['email_id']

            # Combine the dates and times into datetime objects and set the timezones
            tz = pytz.timezone(set_timezone)
            start = datetime.datetime.combine(s_date, s_time)
            start = tz.localize(start)
            if e_date and e_time:
                end = datetime.datetime.combine(e_date, e_time)
                end = tz.localize(end)
            else:
                end = None

            # Get the user's ID
            user_id = User.objects.filter(username=request.user.username).values('id')[0]['id']

            # Create the event and obtain the ID                                     
            e = Event.objects.create(type=1)
            event_id = e.pk
            
            # Save the description
            Event_Description(event_id=event_id,description=detail).save()

            # If an end date/time are provided, then the incident is already closed
            if end:
                Event_Status(event_id=event_id,status=2).save()
            else:
                Event_Status(event_id=event_id,status=1).save()

            # Save the times
            Event_Time(event_id=event_id,start=start,end=end).save()

            # Add the user
            Event_User(event_id=event_id,user_id=user_id).save()

            # Add the email recipient, if requested.
            # Form validation ensures that a valid email is selected if broadcast is selected.  
            if broadcast: 
                Event_Email(event_id=event_id,email_id=email_id).save()

            # Find out which services this impacts and associate the services with the event
            # Form validation confirms that there is at least 1 service
            for service_id in affected_svcs:
                # Should be number only -- can't figure out how to validate
                # multiple checkboxes in the form
                if re.match(r'^\d+$', service_id):
                    Event_Service(service_id=service_id,event_id=event_id).save()


            # Send an email notification to the appropriate list about this issue if requested.  Broadcast won't be
            # allowed to be true if an email address is not defined.
            # Don't send an email if notifications are disabled
            if int(cv.value('notify')) == 1:
                if broadcast:
                    email = notify.email()
                    email.incident(event_id,email_id,set_timezone,True)

            # Send them to the incident detail page for this newly created
            # incident
            return HttpResponseRedirect('/i_detail?id=%s' % event_id)

        # Bad form validation
        else:
            print 'Invalid form: %s.  Errors: %s' % ('AddIncidentForm',form.errors)

    # Not a POST so create a blank form
    else:
        # There are no affected services selected yet
        affected_svcs = []

        form = AddIncidentForm()

    # Obtain all services
    services = Service.objects.values('id','service_name').order_by('service_name')

    # Obtain all current email addresses
    emails = Email.objects.values('id','email')

    # Set the timezone to the user's timezone (otherwise TIME_ZONE will be used)
    jtz.activate(set_timezone)

    # Help message
    help = cv.value('help_create_incident')

    # See if email notifications are enabled
    notifications = int(cv.value('notify'))

    # Obtain the incident description text
    instr_incident_description = cv.value('instr_incident_description')

    # Print the page
    return render_to_response(
       'incidents/incident.html',
       {
          'title':'System Status Dashboard | Create Incident',
          'services':services,
          'emails':emails,
          'affected_svcs':tuple(affected_svcs),
          'form':form,
          'help':help,
          'notifications':notifications,
          'instr_incident_description':instr_incident_description,
          'breadcrumbs':{'Admin':'/admin','Log Incident':'incident'}

       },
       context_instance=RequestContext(request)
    )


@login_required
@staff_member_required
def i_update(request):
    """Update Incident Page

    Update an incident

    """

    # Instantiate the configuration value getter
    cv = config_value.config_value()

    # Obtain the timezone (or set to the default DJango server timezone)
    if request.COOKIES.get('timezone') == None:
        set_timezone = settings.TIME_ZONE
    else:
        set_timezone = request.COOKIES.get('timezone')

    # If this is a POST, then validate the form and save the data
    # Some validation must take place manually (service
    # addition/subtraction
    if request.method == 'POST':

        # If this is a form submit that fails, we want to reset whatever services were selected
        # by the user.  Templates do not allow access to Arrays stored in QueryDict objects so we have
        # to determine the list and send back to the template on failed form submits
        affected_svcs = request.POST.getlist('service')

        # Check the form elements
        form = UpdateIncidentForm(request.POST)

        if form.is_valid():

            # Obtain the cleaned data
            id = form.cleaned_data['id']
            s_date = form.cleaned_data['s_date']
            s_time = form.cleaned_data['s_time']
            e_date = form.cleaned_data['e_date']
            e_time = form.cleaned_data['e_time']
            update = form.cleaned_data['update']
            broadcast = form.cleaned_data['broadcast']
            email_id = form.cleaned_data['email_id']

            # Combine the dates and times into datetime objects and set the timezones
            tz = pytz.timezone(set_timezone)
            start = datetime.datetime.combine(s_date, s_time)
            start = tz.localize(start)
            if e_date and e_time:
                end = datetime.datetime.combine(e_date, e_time)
                end = tz.localize(end)
            else:
                end = None

            # Get the user's ID
            user_id = User.objects.filter(username=request.user.username).values('id')[0]['id']

            # If an end date/time are provided, then the incident is closed
            if end:
                Event_Status.objects.filter(event_id=id).update(status=2)
            else:
                Event_Status.objects.filter(event_id=id).update(status=1)

            # Update the times
            Event_Time.objects.filter(event_id=id).update(start=start,end=end)

            # Add the update, if there is one, using the current time
            if update:
                # Create a datetime object for right now and add the server's timezone (whatever DJango has)
                time_now = datetime.datetime.now()
                time_now = pytz.timezone(settings.TIME_ZONE).localize(time_now)
                Event_Update(event_id=id,date=time_now,update=update,user_id=user_id).save()

            # Add the email recipient.  If an email recipient is missing, then the broadcast email will not be checked.
            # In both cases, delete the existing email (because it will be re-added)
            Event_Email.objects.filter(event_id=id).delete()
            if broadcast: 
                Event_Email(event_id=id,email_id=email_id).save()

            # See if we are adding or subtracting services
            # The easiest thing to do here is remove all affected  
            # services and re-add the ones indicated here

            # Remove first
            Event_Service.objects.filter(event_id=id).delete()
    
            # Now add (form validation confirms that there is at least 1)
            for service_id in affected_svcs:
                # Should be number only -- can't figure out how to validate
                # multiple checkboxes in the form
                if re.match(r'^\d+$', service_id):
                    Event_Service(event_id=id,service_id=service_id).save()

            # Send an email notification to the appropriate list about this issue if requested.  Broadcast won't be
            # allowed to be true if an email address is not defined.
            # Don't send an email if notifications are disabled
            if int(cv.value('notify')) == 1:
                if broadcast:
                    email = notify.email()
                    email.incident(id,email_id,set_timezone,False)
            
                # If broadcast is not selected, turn off emails
                else:
                    Event_Email.objects.filter(event_id=id).delete()


            # All done so redirect to the incident detail page so
            # the new data can be seen.
            return HttpResponseRedirect('/i_detail?id=%s' % id)
        
        # Bad form validation
        else:
            print 'Invalid form: %s.  Errors: %s' % ('UpdateIncidentForm',form.errors)

            # Obtain the id so we can print the update page again
            if 'id' in request.POST: 
                if re.match(r'^\d+$', request.POST['id']):
                    id = request.POST['id']
                else:
                    return system_message(request,True,'Improperly formatted id') 
            else:
                return system_message(request,True,'No incident ID given') 

    # Not a POST so create a blank form
    else:
        # Obtain the id 
        if 'id' in request.GET: 
            if re.match(r'^\d+$', request.GET['id']):
                id = request.GET['id']
            else:
                return system_message(request,True,'Improperly formatted id') 
        else:
            return system_message(request,True,'No incident ID given')

        # In the case of a GET, we can acquire the proper services from the DB
        affected_svcs_tmp = Event.objects.filter(id=id).values('event_service__service_id')
        affected_svcs = []
        for service_id in affected_svcs_tmp:
            affected_svcs.append(service_id['event_service__service_id'])
        affected_svcs = list(affected_svcs)
        
        # Create a blank form
        form = UpdateIncidentForm()

    # Obtain the details
    details = Event.objects.filter(id=id).values(
                                                'event_status__status',
                                                'event_email__email_id',
                                                'event_time__start',
                                                'event_time__end',
                                                'event_status__status'
                                                )

    # Obtain all services
    services = Service.objects.values('id','service_name').order_by('service_name')

    # Obtain all current email addresses
    emails = Email.objects.values('id','email')

    # See if email notifications are enabled
    notifications = int(cv.value('notify'))

    # Obtain the incident update text
    instr_incident_update = cv.value('instr_incident_update')

    # Set the timezone to the user's timezone (otherwise TIME_ZONE will be used)
    jtz.activate(set_timezone)

    # Print the page
    return render_to_response(
       'incidents/i_update.html',
       {
          'title':'System Status Dashboard | Update Incident',
          'details':details,
          'services':services,
          'affected_svcs':affected_svcs,
          'id':id,
          'form':form,
          'emails':emails,
          'notifications':notifications,
          'instr_incident_update':instr_incident_update
       },
       context_instance=RequestContext(request)
    )


@login_required
@staff_member_required
def i_delete(request):
    """Delete Incident Page

    Delete an incident given an id

    """

    # We only accept posts
    if request.method == 'POST':
        
        # Check the form elements
        form = DeleteEventForm(request.POST)

        if form.is_valid():

            # Obtain the cleaned data
            id = form.cleaned_data['id']

            # Delete the incident
            Event.objects.filter(id=id).delete()

            # Redirect to the homepage
            return HttpResponseRedirect('/')

    # If processing got this far, its either not a POST
    # or its an invalid form submit.  Either way, give an error        
    return system_message(request,True,'Invalid delete request')


def i_detail(request):
    """Incident Detail View

    Show all available information on an incident

    """

    form = DetailForm(request.GET)

    if form.is_valid():
        # Obtain the cleaned data
        id = form.cleaned_data['id']

    # Bad form
    else:
        return system_message(request,True,'Improperly formatted id: %s' % (request.GET['id']))

    # Instantiate the configuration value getter
    cv = config_value.config_value()

    # Which services were impacted
    services = Event.objects.filter(id=id).values('event_service__service__service_name')

    # Obain the incident detail
    detail = Event.objects.filter(id=id).values(
                                                'event_time__start',
                                                'event_time__end',
                                                'event_description__description',
                                                'event_email__email__email',
                                                'event_user__user__first_name',
                                                'event_user__user__last_name'
                                                )

    # Obain any incident updates
    updates = Event.objects.filter(id=id).values(
                                                'event_update__id',
                                                'event_update__date',
                                                'event_update__update',
                                                'event_update__user__first_name',
                                                'event_update__user__last_name'
                                                ).order_by('event_update__id')
    # If there are no updates, set to None
    if len(updates) == 1 and updates[0]['event_update__date'] == None:
        updates = None

    # See if an email address is selected
    email_selected = Event.objects.filter(event_email__event_id=id).values('event_email__email__email')

    # See if the timezone is set, if not, give them the server timezone
    if request.COOKIES.get('timezone') == None:
        set_timezone = settings.TIME_ZONE
    else:
        set_timezone = request.COOKIES.get('timezone')

    # See if email notifications are enabled
    notifications = int(cv.value('notify'))

    # Set the timezone to the user's timezone (otherwise TIME_ZONE will be used)
    jtz.activate(set_timezone)

    # Print the page
    return render_to_response(
       'incidents/i_detail.html',
       {
          'title':'System Status Dashboard | Incident Detail',
          'services':services,
          'id':id,
          'detail':detail,
          'updates':updates,
          'notifications':notifications,
          'email_selected':email_selected,
          'breadcrumbs':{'Admin':'/admin','Update Detail':'i_detail'}
       },
       context_instance=RequestContext(request)
    )



