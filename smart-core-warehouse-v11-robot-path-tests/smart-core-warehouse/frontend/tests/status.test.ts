import {describe,it,expect} from 'vitest'
import {statusClass} from '../src/domain/status'
describe('statusClass',()=>{it('normalizes warehouse states',()=>{expect(statusClass('RESERVED_FOR_RETURN')).toBe('s-reserved-for-return')})})
