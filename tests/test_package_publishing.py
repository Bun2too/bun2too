import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.publish_package import commands, matrix, target


class PackagePublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def package(self, **changes):
        data = dict(name='@bun2too/test', version='1.0.0', files=['dist'], scripts={'test':'node test.js'})
        data.update(changes)
        (self.root/'package.json').write_text(json.dumps(data))
        (self.root/'package-lock.json').write_text('{}')

    def test_reject_escape_unknown_kind_and_missing_build(self):
        for kind, directory in [('container', '..'), ('zip', '.'), ('maven', '.')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError): target(self.root, kind, directory)

    def test_npm_namespace_destination_and_distributable_files(self):
        self.package()
        self.assertEqual(target(self.root,'npm','.'),self.root.resolve())
        for changes in [{'name':'@other/test'}, {'private':True}, {'files':[]},
                        {'publishConfig':{'registry':'https://registry.npmjs.org'}}]:
            self.package(**changes)
            with self.assertRaises(ValueError): target(self.root,'npm','.')

    def test_duplicate_targets_fail_and_current_manifest_validates(self):
        (self.root/'Dockerfile').write_text('FROM scratch')
        (self.root/'.github').mkdir()
        item={'kind':'container','directory':'.','image':'test'}
        (self.root/'.github/package-targets.json').write_text(json.dumps({'include':[item,item]}))
        with self.assertRaisesRegex(ValueError,'Duplicate'): matrix(self.root)
        self.assertEqual(matrix(Path(__file__).resolve().parents[1])['include'][0]['kind'],'container')
        (self.root/'second').mkdir(); (self.root/'second/Dockerfile').write_text('FROM scratch')
        (self.root/'.github/package-targets.json').write_text(json.dumps({'include':[
            item,dict(item,directory='second')]}))
        with self.assertRaisesRegex(ValueError,'distinct image'): matrix(self.root)

    def test_commands_test_before_publish_and_pin_registry(self):
        with patch.dict('os.environ', GITHUB_REF_NAME='qa'):
            npm=commands('npm',self.root,'Bun2too/example')
        self.assertLess(npm.index(['npm','test']),len(npm)-1)
        self.assertIn('--registry=https://npm.pkg.github.com',npm[-1])
        self.assertIn('--tag=qa',npm[-1])
        maven=commands('maven',self.root,'Bun2too/example')[0]
        for name in ['altDeploymentRepository','altReleaseDeploymentRepository','altSnapshotDeploymentRepository']:
            self.assertIn('-D'+name+'=github::https://maven.pkg.github.com/bun2too/example',maven)
        gradle=commands('gradle',self.root,'Bun2too/example')
        self.assertEqual(gradle[0][-1],'build')
        self.assertEqual(gradle[-1][-1],'publishAllPublicationsToGitHubPackagesRepository')
        with self.assertRaises(ValueError): commands('npm',self.root,'Other/example')

    def test_deploy_requires_publishing_and_publish_requires_verification(self):
        import yaml
        root=Path(__file__).resolve().parents[1]
        workflow=yaml.safe_load((root/'.github/workflows/deploy.yml').read_text())
        jobs=workflow['jobs']
        self.assertEqual(jobs['packages']['needs'],'verify')
        self.assertIn('packages',jobs['deploy']['needs'])
        self.assertIn("needs.packages.result == 'success'",jobs['deploy']['if'])
        self.assertNotIn('packages',workflow['permissions'])
        self.assertEqual(jobs['packages']['permissions']['packages'],'write')
        publish=yaml.safe_load((root/'.github/workflows/publish-package.yml').read_text())
        steps=publish['jobs']['publish']['steps']
        push=next(s for s in steps if s.get('id')=='image')
        self.assertTrue(push['with']['push'])
        self.assertIn('github.sha',push['with']['tags'])
        self.assertTrue(any('imagetools inspect' in s.get('run','') for s in steps))
