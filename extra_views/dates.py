from calendar import Calendar
from collections import defaultdict
import datetime
import math

from django.views.generic.dates import DateMixin, YearMixin, MonthMixin, _date_from_string
from django.views.generic.list import MultipleObjectTemplateResponseMixin, BaseListView
from django.db. models import Q
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import ugettext_lazy as _

DAYS = (
    _(u'Monday'),
    _(u'Tuesday'),
    _(u'Wednesday'),
    _(u'Thursday'),
    _(u'Friday'),
    _(u'Saturday'),
    _(u'Sunday'),
)

def daterange(start_date, end_date):
    """
    Returns an iterator of dates between two provided ones
    """
    for n in range(int((end_date - start_date).days + 1)):
        yield start_date + datetime.timedelta(n)


class BaseCalendarMonthView(DateMixin, YearMixin, MonthMixin, BaseListView):
    first_of_week = 0  # 0 = Monday, 6 = Sunday
    paginate_by = None  # We don't want to use this part of MultipleObjectMixin
    date_field = None
    end_date_field = None  # For supporting events with duration

    def get_paginate_by(self, queryset):
        if self.paginate_by is not None:
            raise ImproperlyConfigured(u"'%s' cannot be paginated, it is a calendar view" % self.__class__.__name__)
        return None

    def get_allow_future(self):
        return True

    def get_end_date_field(self):
        return self.end_date_field

    def get_start_date(self, obj):
        obj_date = getattr(obj, self.get_date_field())
        try:
            obj_date = obj_date.date()
        except AttributeError:
            # It's a date rather than datetime, so we use it as is
            pass
        return obj_date

    def get_end_date(self, obj):
        obj_date = getattr(obj, self.get_end_date_field())
        try:
            obj_date = obj_date.date()
        except AttributeError:
            # It's a date rather than datetime, so we use it as is
            pass
        return obj_date


    def get_first_of_week(self):
        if self.first_of_week is None:
            raise ImproperlyConfigured("%s.first_of_week is required." % self.__class__.__name__)
        if self.first_of_week not in range(7):
            raise ImproperlyConfigured("%s.first_of_week must be an integer between 0 and 6." % self.__class__.__name__)
        return self.first_of_week

    def get_queryset(self):
        qs = super(BaseCalendarMonthView, self).get_queryset()

        year = self.get_year()
        month = self.get_month()

        date_field = self.get_date_field()
        end_date_field = self.get_end_date_field()

        date = _date_from_string(year, self.get_year_format(),
                                 month, self.get_month_format())

        since = date
        until = self.get_next_month(date)

        # Adjust our start and end dates to allow for next and previous
        # month edges
        if since.weekday() != self.get_first_of_week():
            diff = math.fabs(since.weekday() - self.get_first_of_week())
            since = since - datetime.timedelta(days=diff)

        if until.weekday() != ((self.get_first_of_week() + 6) % 7):
            diff = math.fabs(((self.get_first_of_week() + 6) % 7) - until.weekday())
            until = until + datetime.timedelta(days=diff)

        if end_date_field:
            # 5 possible conditions for showing an event:

            # 1) Single day event, starts after 'since'
            # 2) Multi-day event, starts after 'since' and ends before 'until'
            # 3) Starts before 'since' and ends after 'since' and before 'until'
            # 4) Starts after 'since' but before 'until' and ends after 'until'
            # 5) Starts before 'since' and ends after 'until'
            predicate1 = Q(**{
                '%s__gte' % date_field: since,
                end_date_field: None
            })
            predicate2 = Q(**{
                '%s__gte' % date_field: since,
                '%s__lt' % end_date_field: until
            })
            predicate3 = Q(**{
                '%s__lt' % date_field: since,
                '%s__gte' % end_date_field: since,
                '%s__lt' % end_date_field: until
            })
            predicate4 = Q(**{
                '%s__gte' % date_field: since,
                '%s__lt' % date_field: until,
                '%s__gte' % end_date_field: until
            })
            predicate5 = Q(**{
                '%s__lt' % date_field: since,
                '%s__gte' % end_date_field: until
            })
            return qs.filter(predicate1 | predicate2 | predicate3| predicate4 | predicate5)
        return qs.filter(**{
            '%s__gte' % date_field: since
        })

    def get_context_data(self, **kwargs):
        data = super(BaseCalendarMonthView, self).get_context_data(**kwargs)

        year = self.get_year()
        month = self.get_month()

        date = _date_from_string(year, self.get_year_format(),
                                 month, self.get_month_format())

        cal = Calendar(self.get_first_of_week())

        month_calendar = []
        now = datetime.datetime.utcnow()

        date_lists = defaultdict(list)
        multidate_objs = []

        for obj in data['object_list']:
            obj_date = self.get_start_date(obj)
            end_date_field = self.get_end_date_field()

            if end_date_field:
                end_date = self.get_end_date(obj)

                if end_date and end_date != obj_date:
                    multidate_objs.append({
                        'obj': obj,
                        'range': [x for x in daterange(obj_date, end_date)]
                    })
                    continue  # We don't put multi-day events in date_lists

            date_lists[obj_date].append(obj)

        for week in cal.monthdatescalendar(date.year, date.month):
            week_range = set(daterange(week[0], week[6]))
            week_objects = []

            for val in multidate_objs:
                if week_range.intersection(val['range']):
                    # Event happens during this week
                    slot = 1
                    width = 7
                    wrap_previous = True
                    wrap_next = True

                    if val['range'][0] >= week[0]:
                        slot = 1 + (val['range'][0] - week[0]).days
                        wrap_next = False
                    if val['range'][-1] <= week[6]:
                        end_offset = 7 - (week[6] - val['range'][-1]).days
                        width = 1 + (end_offset - slot)
                        wrap_previous = False

                    week_objects.append({
                        'obj': val['obj'],
                        'slot': slot,
                        'width': width,
                        'wrap_previous': wrap_previous,
                        'wrap_next': wrap_next,
                    })

            week_calendar = {
                'multidate_objs': week_objects,
                'date_list': [],
            }
            for day in week:
                week_calendar['date_list'].append({
                    'day': day,
                    'object_list': date_lists[day],
                    'today': day == now.date(),
                    'is_current_month': day.month == date.month,
                })
            month_calendar.append(week_calendar)

        data['calendar'] = month_calendar
        data['weekdays'] = [DAYS[x] for x in cal.iterweekdays()]
        data['month'] = date
        data['next_month'] = self.get_next_month(date)
        data['previous_month'] = self.get_previous_month(date)

        return data


class CalendarMonthView(MultipleObjectTemplateResponseMixin, BaseCalendarMonthView):
    template_name_suffix = '_calendar_month'