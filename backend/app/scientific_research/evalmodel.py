"""Deterministic smoke-test responses, never used as evidence of model quality.

The fixture reads source text but never reads human scores or expected answers.
"""
from .demo import DemoModel


class BaselineFixtureModel(DemoModel):
    identity = 'scientific-eval-fixture-v1'

    def __init__(self, simulation='normal'):
        self.simulation = simulation

    async def complete(self, role, system, context):
        if self.simulation == 'timeout' and role == 'reader':
            raise TimeoutError('Injected local fixture timeout')
        if role == 'reader':
            result = await super().complete(role, system, context)
            if self.simulation == 'bad_quote':
                result['claims'][0]['quote'] = 'INJECTED QUOTE NOT IN THE FROZEN MATERIAL'
            return result
        result = await super().complete(role, system, context)
        if role == 'synthesizer' and self.simulation == 'foreign_reference':
            result['findings'][0]['evidence_ids'] = ['not-a-retrieved-evidence-id']
        if role == 'synthesizer' and self.simulation == 'english_analysis':
            result['findings'][0]['text'] = 'Synthetic English-only analysis; this is not scientific evidence.'
        if role == 'proposer':
            direction = result['directions'][0]
            direction.update(question='合成测试：如何检验时空模型跨区域泛化？',
                             minimal_experiment='合成测试：固定预算，留出区域，对比预测误差。')
            if self.simulation == 'excluded_direction':
                direction['minimal_experiment'] = '使用 PM2.5 预测任务检验模型。'
        return result
