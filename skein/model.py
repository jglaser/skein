from __future__ import absolute_import, print_function, division

import json
import os
from datetime import datetime, timedelta

import yaml

from . import proto as _proto
from .compatibility import urlparse
from .utils import implements, format_list

__all__ = ('Job', 'Service', 'Resources', 'File', 'ResourceUsageReport',
           'ApplicationReport')


required = type('required', (object,),
                {'__repr__': lambda s: 'required'})()


_EPOCH = datetime(1970, 1, 1)


def _datetime_from_millis(x):
    return _EPOCH + timedelta(milliseconds=x)


def _if_none(x, y):
    return x if x is not None else y


def is_list_of(x, typ):
    return isinstance(x, list) and all(isinstance(i, typ) for i in x)


def is_dict_of(x, ktyp, vtyp):
    return (isinstance(x, dict) and
            all(isinstance(k, ktyp) for k in x.keys()) and
            all(isinstance(v, vtyp) for v in x.values()))


def _convert(x, method, *args):
    if hasattr(x, method):
        return getattr(x, method)(*args)
    elif type(x) is list:
        return [_convert(i, method, *args) for i in x]
    elif type(x) is dict:
        return {k: _convert(v, method, *args) for k, v in x.items()}
    elif type(x) is datetime:
        return int(x.timestamp() * 1000)
    else:
        return x


def _infer_format(path, format='infer'):
    if format is 'infer':
        _, ext = os.path.splitext(path)
        if ext == '.json':
            format = 'json'
        elif ext in {'.yaml', '.yml'}:
            format = 'yaml'
        else:
            raise ValueError("Can't infer format from filepath %r, please "
                             "specify manually" % path)
    elif format not in {'json', 'yaml'}:
        raise ValueError("Unknown file format: %r" % format)
    return format


class Base(object):
    __slots__ = ()

    def __eq__(self, other):
        return (type(self) == type(other) and
                all(getattr(self, k) == getattr(other, k)
                    for k in self.__slots__))

    @classmethod
    def _check_keys(cls, obj, keys=None):
        keys = keys or cls.__slots__
        if not isinstance(obj, dict):
            raise TypeError("Expected mapping for %r" % cls.__name__)
        extra = set(obj).difference(keys)
        if extra:
            raise ValueError("Unknown extra keys for %s:\n"
                             "%s" % (cls.__name__, format_list(extra)))

    def _check_required(self):
        for k in self.__slots__:
            if getattr(self, k) is required:
                raise TypeError("parameter %r is required but wasn't "
                                "provided" % k)

    def _check_in_set(self, field, values):
        if getattr(self, field) not in values:
            raise ValueError("%s must be in %r" % (field, values))

    def _check_is_type(self, field, type, nullable=False):
        val = getattr(self, field)
        if not (isinstance(val, type) or (nullable and val is None)):
            if nullable:
                msg = "%s must be an instance of %s, or None"
            else:
                msg = "%s must be an instance of %s"
            raise TypeError(msg % (field, type.__name__))

    def _check_is_list_of(self, field, type, nullable=False):
        val = getattr(self, field)
        if not (is_list_of(val, type) or (nullable and val is None)):
            if nullable:
                msg = "%s must be a list of %s, or None"
            else:
                msg = "%s must be a list of %s"
            raise TypeError(msg % (field, type.__name__))

    def _check_is_dict_of(self, field, key, val, nullable=False):
        attr = getattr(self, field)
        if not (is_dict_of(attr, key, val) or (nullable and attr is None)):
            if nullable:
                msg = "%s must be a dict of %s -> %s, or None"
            else:
                msg = "%s must be a list of %s -> %s"
            raise TypeError(msg % (field, key.__name__, val.__name__))

    def _check_is_bounded_int(self, field, min=0, nullable=False):
        x = getattr(self, field)
        self._check_is_type(field, int, nullable=nullable)
        if x is not None and x < min:
            raise ValueError("%s must be >= %d" % (field, min))

    @classmethod
    def from_protobuf(cls, msg):
        """Create an instance from a protobuf message."""
        if not isinstance(msg, cls._protobuf_cls):
            raise TypeError("Expected message of type "
                            "%r" % cls._protobuf_cls.__name__)
        kwargs = {k: getattr(msg, k) for k in cls.__slots__}
        return cls(**kwargs)

    @classmethod
    def from_dict(cls, obj):
        """Create an instance from a dict.

        Keys in the dict should match parameter names"""
        cls._check_keys(obj)
        return cls(**obj)

    @classmethod
    def from_json(cls, b):
        """Create an instance from a json string.

        Keys in the json object should match parameter names"""
        return cls.from_dict(json.loads(b))

    @classmethod
    def from_yaml(cls, b):
        """Create an instance from a yaml string."""
        return cls.from_dict(yaml.safe_load(b))

    @classmethod
    def from_file(cls, path, format='infer'):
        """Create an instance from a json or yaml file.

        Parameter
        ---------
        path : str
            The path to the file to load.
        format : {'infer', 'json', 'yaml'}, optional
            The file format. By default the format is inferred from the file
            extension.
        """
        format = _infer_format(path, format=format)

        if format == 'json':
            with open(path) as f:
                data = f.read()
            return cls.from_json(data)
        else:
            with open(path) as f:
                data = yaml.safe_load(f)
            return cls.from_dict(data)

    def to_protobuf(self):
        """Convert object to a protobuf message"""
        self._validate()
        kwargs = {k: _convert(getattr(self, k), 'to_protobuf')
                  for k in self.__slots__}
        return self._protobuf_cls(**kwargs)

    def to_dict(self, skip_nulls=True):
        """Convert object to a dict"""
        self._validate()
        out = {}
        for k in self.__slots__:
            val = getattr(self, k)
            if not skip_nulls or val is not None:
                out[k] = _convert(val, 'to_dict', skip_nulls)
        return out

    def to_json(self, skip_nulls=True):
        """Convert object to a json string"""
        return json.dumps(self.to_dict(skip_nulls=skip_nulls))

    def to_yaml(self, skip_nulls=True):
        """Convert object to a yaml string"""
        return yaml.dump(self.to_dict(skip_nulls=skip_nulls),
                         default_flow_style=False)

    def to_file(self, path, format='infer', skip_nulls=True):
        """Write object to a file.

        Parameter
        ---------
        path : str
            The path to the file to load.
        format : {'infer', 'json', 'yaml'}, optional
            The file format. By default the format is inferred from the file
            extension.
        skip_nulls : bool, optional
            By default null values are skipped in the output. Set to True to
            output all fields.
        """
        format = _infer_format(path, format=format)
        data = getattr(self, 'to_' + format)(skip_nulls=skip_nulls)
        with open(path, mode='w') as f:
            f.write(data)


class Resources(Base):
    """Resource requests per container.

    Parameters
    ----------
    memory : int
        The memory to request, in MB
    vcores : int
        The number of virtual cores to request.
    """
    __slots__ = ('memory', 'vcores')
    _protobuf_cls = _proto.Resources

    def __init__(self, memory=required, vcores=required):
        self.memory = memory
        self.vcores = vcores

        self._check_required()
        self._validate()

    def __repr__(self):
        return 'Resources<memory=%d, vcores=%d>' % (self.memory, self.vcores)

    def _validate(self, is_request=False):
        min = 1 if is_request else 0
        self._check_is_bounded_int('vcores', min=min)
        self._check_is_bounded_int('memory', min=min)


class File(Base):
    """A file/archive to distribute with the service.

    Parameters
    ----------
    source : str
        The path to the file/archive. If no scheme is specified, path is
        assumed to be on the local filesystem (``file://`` scheme).
    type : {'FILE', 'ARCHIVE'}, optional
        The type of file to distribute. Archive's are automatically extracted
        by yarn into a directory with the same name as ``dest``. Default is
        ``'FILE'``.
    visibility : {'APPLICATION', 'PUBLIC', 'PRIVATE'}, optional
        The resource visibility, default is ``'APPLICATION'``
    size : int, optional
        The resource size in bytes. If not provided will be determined by the
        file system.
    timestamp : int, optional
        The time the resource was last modified. If not provided will be
        determined by teh file system.
    """
    __slots__ = ('source', 'type', 'visibility', 'size', 'timestamp')
    _protobuf_cls = _proto.File

    def __init__(self, source=required, type='FILE', visibility='APPLICATION',
                 size=0, timestamp=0):
        self.source = source
        self.type = type
        self.visibility = visibility
        self.size = size
        self.timestamp = timestamp

        self._check_required()
        self._validate()

    def __repr__(self):
        return 'File<source=%r, type=%r>' % (self.source, self.type)

    def _validate(self):
        self._check_is_type('source', str)
        self._check_in_set('type', {'FILE', 'ARCHIVE'})
        self._check_in_set('visibility', {'APPLICATION', 'PUBLIC', 'PRIVATE'})
        self._check_is_bounded_int('size')
        self._check_is_bounded_int('timestamp')

    @classmethod
    @implements(Base.from_protobuf)
    def from_protobuf(cls, obj):
        if not isinstance(obj, cls._protobuf_cls):
            raise TypeError("Expected message of type "
                            "%r" % cls._protobuf_cls.__name__)
        return cls(source=obj.source,
                   type=_proto.File.Type.Name(obj.type),
                   visibility=_proto.File.Visibility.Name(obj.visibility),
                   size=obj.size,
                   timestamp=obj.timestamp)

    @classmethod
    def _parse_file_spec(cls, obj):
        if not isinstance(obj, dict):
            raise TypeError("Expected mapping for File")

        if 'file' in obj:
            if 'archive' in obj:
                raise ValueError("Both 'archive' and 'file' specified")
            type = 'file'
        elif 'archive' in obj:
            type = 'archive'
        else:
            type = None

        if type is None:
            cls._check_keys(obj, cls.__slots__ + ('dest',))
            source = obj['source']
            type = obj.get('type', 'FILE').upper()
        else:
            cls._check_keys(obj, ('visibility', 'size', 'timestamp',
                                  type, 'dest'))
            source = obj[type]
            type = type.upper()

        if 'dest' not in obj:
            source = urlparse(source).path
            base, name = os.path.split(source)
            if name is None:
                raise ValueError("Distributed files must be files/archives, "
                                 "not directories")
            dest = name
            if type == 'ARCHIVE':
                for ext in ['.zip', '.tar.gz', '.tgz']:
                    if name.endswith(ext):
                        dest = name[:-len(ext)]
                        break
        else:
            dest = obj['dest']

        visibility = obj.get('visibility', 'APPLICATION')
        size = obj.get('size', 0)
        timestamp = obj.get('timestamp', 0)

        resource = cls(source=source, type=type, visibility=visibility,
                       size=size, timestamp=timestamp)

        return dest, resource


class Service(Base):
    """Description of a Skein service.

    Parameters
    ----------
    commands : list
        Shell commands to startup the service. Commands are run in the order
        provided, with subsequent commands only run if the prior commands
        succeeded. At least one command must be provided
    resources : Resources
        Describes the resources needed to run the service.
    instances : int, optional
        The number of instances to create on startup. Default is 1.
    files : dict, optional
        Describes any files needed to run the service. A mapping of destination
        relative paths to ``File`` objects describing the sources for these
        paths.
    env : dict, optional
        A mapping of environment variables needed to run the service.
    depends : list, optional
        A list of string keys in the keystore that this service depends on. The
        service will not be started until these keys are present.
    """
    __slots__ = ('commands', 'resources', 'instances', 'files', 'env',
                 'depends')
    _protobuf_cls = _proto.Service

    def __init__(self, commands=required, resources=required, instances=1,
                 files=None, env=None, depends=None):
        self.commands = commands
        self.resources = resources
        self.instances = instances
        self.files = _if_none(files, {})
        self.env = _if_none(env, {})
        self.depends = _if_none(depends, [])

        self._check_required()
        self._validate()

    def __repr__(self):
        return 'Service<instances=%d, ...>' % self.instances

    def _validate(self):
        self._check_is_bounded_int('instances', min=0)

        self._check_is_type('resources', Resources)
        self.resources._validate(is_request=True)

        self._check_is_dict_of('files', str, File)
        for f in self.files.values():
            f._validate()

        self._check_is_dict_of('env', str, str)

        self._check_is_list_of('commands', str)
        if not self.commands:
            raise ValueError("There must be at least one command")

        self._check_is_list_of('depends', str)

    @classmethod
    @implements(Base.from_dict)
    def from_dict(cls, obj):
        cls._check_keys(obj, cls.__slots__)

        resources = obj.get('resources')
        if resources is not None:
            resources = Resources.from_dict(resources)

        files = obj.get('files')

        if files is not None:
            if isinstance(files, list):
                files = dict(File._parse_file_spec(v) for v in files)
            elif isinstance(files, dict):
                files = {k: File.from_dict(v) for k, v in files.items()}

        kwargs = {'resources': resources,
                  'files': files,
                  'env': obj.get('env'),
                  'commands': obj.get('commands'),
                  'depends': obj.get('depends')}

        if 'instances' in obj:
            kwargs['instances'] = obj['instances']

        return cls(**kwargs)

    @classmethod
    @implements(Base.from_protobuf)
    def from_protobuf(cls, obj):
        resources = Resources.from_protobuf(obj.resources)
        files = {k: File.from_protobuf(v) for k, v in obj.files.items()}
        kwargs = {'instances': obj.instances,
                  'resources': resources,
                  'files': files,
                  'env': dict(obj.env),
                  'commands': list(obj.commands),
                  'depends': list(obj.depends)}
        return cls(**kwargs)


class Job(Base):
    """A single Skein job.

    Parameters
    ----------
    services : dict
        A mapping of service-name to services. At least one service is required.
    name : string, optional
        The name of the application, defaults to 'skein'.
    queue : string, optional
        The queue to submit to. Defaults to the default queue.
    """
    __slots__ = ('name', 'queue', 'services')
    _protobuf_cls = _proto.Job

    def __init__(self, services=required, name='skein', queue=''):
        self.services = services
        self.name = name
        self.queue = queue

        self._check_required()
        self._validate()

    def __repr__(self):
        return 'Job<name=%r, queue=%r, services=...>' % (self.name, self.queue)

    def _validate(self):
        self._check_is_type('name', str)
        self._check_is_type('queue', str, nullable=True)
        self._check_is_dict_of('services', str, Service)
        if not self.services:
            raise ValueError("There must be at least one service")
        for s in self.services.values():
            s._validate()

    @classmethod
    @implements(Base.from_dict)
    def from_dict(cls, obj):
        cls._check_keys(obj)

        name = obj.get('name')
        queue = obj.get('queue')

        services = obj.get('services')
        if services is not None and isinstance(services, dict):
            services = {k: Service.from_dict(v) for k, v in services.items()}

        return cls(name=name, queue=queue, services=services)

    @classmethod
    @implements(Base.from_protobuf)
    def from_protobuf(cls, obj):
        services = {k: Service.from_protobuf(v)
                    for k, v in obj.services.items()}
        return cls(name=obj.name,
                   queue=obj.queue,
                   services=services)


def _to_camel_case(x):
    parts = x.split('_')
    return parts[0] + ''.join(x.title() for x in parts[1:])


class ResourceUsageReport(Base):
    __slots__ = ('memory_seconds', 'vcore_seconds', 'num_used_containers',
                 'needed_resources', 'reserved_resources', 'used_resources')
    _protobuf_cls = _proto.ResourceUsageReport

    _keys = tuple(_to_camel_case(k) for k in __slots__)

    def __init__(self, memory_seconds, vcore_seconds, num_used_containers,
                 needed_resources, reserved_resources, used_resources):
        self.memory_seconds = memory_seconds
        self.vcore_seconds = vcore_seconds
        self.num_used_containers = num_used_containers
        self.needed_resources = needed_resources
        self.reserved_resources = reserved_resources
        self.used_resources = used_resources

        self._validate()

    def __repr__(self):
        return 'ResourceUsageReport<...>'

    def _validate(self):
        for k in ['memory_seconds', 'vcore_seconds', 'num_used_containers']:
            self._check_is_bounded_int(k)
        for k in ['needed_resources', 'reserved_resources', 'used_resources']:
            self._check_is_type(k, Resources)
            getattr(self, k)._validate()

    @classmethod
    @implements(Base.from_dict)
    def from_dict(cls, obj):
        cls._check_keys(obj, cls._keys)
        kwargs = dict(memory_seconds=obj['memorySeconds'],
                      vcore_seconds=obj['vcoreSeconds'],
                      num_used_containers=max(0, obj['numUsedContainers']))
        for k, k2 in [('needed_resources', 'neededResources'),
                      ('reserved_resources', 'reservedResources'),
                      ('used_resources', 'usedResources')]:
            val = obj[k2]
            kwargs[k] = Resources(vcores=max(0, val['vcores']),
                                  memory=max(0, val['memory']))
        return cls(**kwargs)

    @classmethod
    @implements(Base.from_protobuf)
    def from_protobuf(cls, obj):
        kwargs = dict(memory_seconds=obj.memory_seconds,
                      vcore_seconds=obj.vcore_seconds,
                      num_used_containers=obj.num_used_containers)
        for k in ['needed_resources', 'reserved_resources', 'used_resources']:
            kwargs[k] = Resources.from_protobuf(getattr(obj, k))
        return cls(**kwargs)


class ApplicationReport(Base):
    __slots__ = ('id', 'name', 'user', 'queue', 'tags', 'host', 'port',
                 'tracking_url', 'state', 'final_status', 'progress', 'usage',
                 'diagnostics', 'start_time', 'finish_time')
    _protobuf_cls = _proto.ApplicationReport

    _keys = tuple(_to_camel_case(k) for k in __slots__)

    def __init__(self, id, name, user, queue, tags, host, port,
                 tracking_url, state, final_status, progress, usage,
                 diagnostics, start_time, finish_time):
        self.id = id
        self.name = name
        self.user = user
        self.queue = queue
        self.tags = tags
        self.host = host
        self.port = port
        self.tracking_url = tracking_url
        self.state = state
        self.final_status = final_status
        self.progress = progress
        self.usage = usage
        self.diagnostics = diagnostics
        self.start_time = start_time
        self.finish_time = finish_time

        self._validate()

    def __repr__(self):
        return 'ApplicationReport<name=%r>' % self.name

    def _validate(self):
        self._check_is_type('id', str)
        self._check_is_type('name', str)
        self._check_is_type('user', str)
        self._check_is_type('queue', str)
        self._check_is_list_of('tags', str)
        self._check_is_type('host', str, nullable=True)
        self._check_is_type('port', int, nullable=True)
        self._check_is_type('tracking_url', str, nullable=True)
        self._check_is_type('state', str)
        self._check_is_type('final_status', str)
        self._check_is_type('progress', float)
        self._check_is_type('usage', ResourceUsageReport)
        self.usage._validate()
        self._check_is_type('diagnostics', str, nullable=True)
        self._check_is_type('start_time', datetime)
        self._check_is_type('finish_time', datetime)

    @classmethod
    @implements(Base.from_dict)
    def from_dict(cls, obj):
        cls._check_keys(obj, cls._keys)
        kwargs = {k: obj.get(k2) for k, k2 in zip(cls.__slots__, cls._keys)}
        kwargs['usage'] = ResourceUsageReport.from_dict(kwargs['usage'])
        for k in ['start_time', 'finish_time']:
            kwargs[k] = _datetime_from_millis(kwargs[k])
        return cls(**kwargs)

    @classmethod
    @implements(Base.from_protobuf)
    def from_protobuf(cls, obj):
        return cls(id=obj.id,
                   name=obj.name,
                   user=obj.user,
                   queue=obj.queue,
                   tags=list(obj.tags),
                   host=obj.host,
                   port=obj.port,
                   tracking_url=obj.tracking_url,
                   state=_proto.ApplicationState.Type.Name(obj.state),
                   final_status=_proto.FinalStatus.Type.Name(obj.final_status),
                   progress=obj.progress,
                   usage=ResourceUsageReport.from_protobuf(obj.usage),
                   diagnostics=obj.diagnostics,
                   start_time=_datetime_from_millis(obj.start_time),
                   finish_time=_datetime_from_millis(obj.finish_time))