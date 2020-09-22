# -*- coding: utf-8 -*-

import logging
import io
import os

from django.db import transaction
from django.core.mail import send_mail
from django.apps import apps
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage

from PIL import Image

from .conf import settings
from . import signals

logger = logging.getLogger(__name__)


# XXX support custom task manager __import__('foo.task')?
def task_manager(tm):
    if tm == 'celery':
        from celery import shared_task
        def task(t):
            t = shared_task(t)
            def _task(*args, **kwargs):
                return t.delay(*args, **kwargs)
            return _task
        return task
    if tm == 'huey':
        from huey.contrib.djhuey import db_task
        return db_task()
    assert tm is None
    return lambda t: t

task = task_manager(settings.ST_TASK_MANAGER)


def periodic_task_manager(tm):
    if tm == 'huey':
        from huey import crontab
        from huey.contrib.djhuey import db_periodic_task
        def periodic_task(hours):
            return db_periodic_task(crontab(
                minute='0', hour='*/{}'.format(hours)))
        return periodic_task
    assert tm in ('celery', None)
    def fake_periodic_task(*args, **kwargs):
        return task_manager(tm)
    return fake_periodic_task

periodic_task = periodic_task_manager(settings.ST_TASK_MANAGER)


def delayed_task(t):
    t = task(t)  # wrap at import time
    def delayed_task_inner(*args, **kwargs):
        transaction.on_commit(lambda: t(*args, **kwargs))
    return delayed_task_inner


@delayed_task
def send_email(subject, message, from_email, recipients):
    # Avoid retrying this task. It's better to log the exception
    # here instead of possibly spamming users on retry
    # We send to one recipient at the time, because otherwise
    # it'll likely get flagged as spam, or it won't reach the
    # the recipient at all
    for recipient in recipients:
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=[recipient])
        except OSError as err:
            logger.exception(err)
            return  # bail out


@delayed_task
def search_index_update(topic_pk):
    # Indexing is too expensive; bail if
    # there's no dedicated task manager
    if settings.ST_TASK_MANAGER is None:
        return
    Topic = apps.get_model('spirit_topic.Topic')
    signals.search_index_update.send(
        sender=Topic,
        instance=Topic.objects.get(pk=topic_pk))


@periodic_task(hours=settings.ST_SEARCH_INDEX_UPDATE_HOURS)
def full_search_index_update():
    age = settings.ST_SEARCH_INDEX_UPDATE_HOURS
    call_command("update_index", age=age)


@delayed_task
def make_avatars(user_id):
    def crop_max_square(image):
        w, h = image.size
        wh = min(w, h)
        x = max(0, (w - wh) // 2)
        y = max(0, (h - wh) // 2)
        return image.crop((x, y, x+wh, y+wh))
    def resize_max(image, to):
        assert min(image.size) == max(image.size), 'not a square'
        if max(image.size) <= to:
            return image
        return image.resize((to, to), resample=Image.BICUBIC)
    def to_file(image):
        buff = io.BytesIO()
        image.save(buff, format='JPEG', subsampling=0, quality=90)
        return SimpleUploadedFile(
            'pic.jpg', content=buff.getvalue(), content_type='image/jpeg')
    def make_small_avatar(name, image):
        image = resize_max(image, 100)
        file = to_file(image)
        name, ext = os.path.splitext(name)
        default_storage.save('{}_small{}'.format(name, ext), file)
    User = get_user_model()
    user = User.objects.get(pk=user_id)
    user.st.avatar.open()
    image = Image.open(user.st.avatar)
    square_image = crop_max_square(image)
    image = resize_max(square_image, 300)
    file = to_file(image)
    # delete original even for overwrite storage,
    # as it may have other extension
    user.st.avatar.delete()
    user.st.avatar.save('pic.jpg', file)
    user.st.save()
    make_small_avatar(user.st.avatar.name, square_image)


@delayed_task
def clean_sessions():
    pass


@delayed_task
def backup_database():
    pass

