# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Metadata extractor for FSL FEAT results

This uses the NIDM results implementation for FSL.

"""


from datalad_metalad.extractors.base import MetadataExtractor
from datalad_metalad import (
    get_file_id,
)
from six import (
    text_type,
)
from datalad.support.json_py import (
    load as jsonload,
    loads as jsonloads,
    dump as jsondump,
)
from datalad.utils import (
    Path,
    make_tempfile,
)
import logging
lgr = logging.getLogger('datalad.metadata.extractors.fslfeat')


class FSLFEATExtractor(MetadataExtractor):
    def __call__(self, dataset, refcommit, process_type, status):
        # shortcut
        ds = dataset

        feat_dirs = _get_feat_dirs(status)
        if not feat_dirs:
            return

        context = None
        extracts = []
        for fd in feat_dirs:
            idmap = {
                s['path']: get_file_id(s)
                for s in status
                if fd in Path(s['path']).parents
            }
            # TODO protect against failure and yield error result
            res = _extract_nidmfsl(fd, idmap)
            if '@context' not in res or '@graph' not in res:
                # this is an unexpected output, fail, we cannot work with it
                # TODO error properly
                raise ValueError('not an expected report')
            # context is assumed to not vary across reports
            context = res['@context']
            graph = res['@graph']
            if isinstance(graph, list):
                extracts.extend(graph)
            elif isinstance(graph, dict):
                # this should not happen
                extracts.append(graph)
            else:
                raise ValueError('unexpected report structure')

        yield dict(
            metadata={
                '@context': [
                    context,
                    # amend upstream context with info on datalad IDs
                    {
                        "datalad": "http://dx.datalad.org/",
                    },
                ],
                '@graph': extracts,
            },
            type='dataset',
            status='ok',
        )

    def get_required_content(self, dataset, process_type, status):
        # report anything inside any feat dir
        # TODO which files are really needed for nidmfsl
        # (can we skip, e.g. res4d.nii.gz)?
        feat_dirs = _get_feat_dirs(status)
        return [
            s
            for s in status
            if any(f in Path(s['path']).parents for f in feat_dirs)
            and not Path(s['path']).parent == 'logs'
        ]


def _get_feat_dirs(status):
    feat_dirs = [
        Path(s['path']).parent
        for s in status
        if Path(s['path']).name == 'design.fsf'
    ]
    # find higher level analysis subset
    gfeat_dirs = set(d for d in feat_dirs if d.suffix == '.gfeat')
    # strip contrast feat dirs from high-level analyses (processed
    # internally by nidmfsl)
    feat_dirs = [d for d in feat_dirs
                 if not any(g in d.parents for g in gfeat_dirs)]
    return feat_dirs


def _extract_nidmfsl(feat_dir, idmap):
    from prov.model import Namespace

    def _map_ids(parentobj, fileobj):
        from prov.model import Namespace
        ns = Namespace('datalad', 'http://dx.datalad.org/')
        id_ = idmap.get(fileobj.path, None)
        if id_ is None:
            # fail-safe, change nothing
            id_ = fileobj.id
        else:
            id_ = ns[id_.split(':', 1)[-1]]
        fileobj.id = id_
        parentobj.id = id_

    from nidmfsl.fsl_exporter.fsl_exporter import FSLtoNIDMExporter

    from mock import patch
    with make_tempfile(mkdir=True) as tmpdir, \
            patch(
                'nidmresults.objects.generic.NIDMObject._map_fileid',
                _map_ids):
        exporter = FSLtoNIDMExporter(
            out_dirname=tmpdir,
            zipped=False,
            feat_dir=text_type(feat_dir),
            # this is all fake, we cannot know it, but NIDM FSL wants it
            # TODO try fishing it out from the result again
            groups=[['control', 1]])
        exporter.parse()
        outdir = exporter.export()
        json_s = (Path(outdir) / 'nidm.json').read_text()
        json_s = json_s.replace('http://dx.datalad.org/', 'datalad:')
        md = jsonloads(json_s)
    return md
